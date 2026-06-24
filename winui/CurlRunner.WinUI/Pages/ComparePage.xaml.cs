using CurlRunner.WinUI.Models;
using CurlRunner.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Collections.ObjectModel;
using System.Text.Json;

namespace CurlRunner.WinUI.Pages;

public sealed partial class ComparePage : Page
{
    private readonly Dictionary<string, TextBox> _outputBoxes = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<(TextBox Box, int Start, int Length)> _matches = [];
    private int _matchIndex = -1;
    private bool _isReady;

    public ObservableCollection<ComparePanelModel> Panels { get; } = [];

    public ComparePage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
        Panels.Add(new ComparePanelModel { Name = "Panel 1" });
        Panels.Add(new ComparePanelModel { Name = "Panel 2" });
        RefreshSearchScope();
        _isReady = true;
    }

    private void AddPanel_Click(object sender, RoutedEventArgs e)
    {
        Panels.Add(new ComparePanelModel { Name = $"Panel {Panels.Count + 1}" });
        RefreshSearchScope();
    }

    private async void RenamePanel_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is not ComparePanelModel panel)
        {
            return;
        }
        var input = new TextBox { Text = panel.Name, PlaceholderText = "Panel name" };
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot, Title = "Rename panel", Content = input, PrimaryButtonText = "Rename",
            CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() == ContentDialogResult.Primary && !string.IsNullOrWhiteSpace(input.Text))
        {
            panel.Name = input.Text.Trim();
            RefreshSearchScope(panel);
        }
    }

    private void RemovePanel_Click(object sender, RoutedEventArgs e)
    {
        if (Panels.Count <= 2 || (sender as Button)?.Tag is not ComparePanelModel panel)
        {
            return;
        }
        Panels.Remove(panel);
        _outputBoxes.Remove(panel.Id);
        RefreshSearchScope();
    }

    private void LoadTabs_Click(object sender, RoutedEventArgs e)
    {
        var tabs = AppServices.Workspace.OpenTabs.Where(tab => !string.IsNullOrWhiteSpace(tab.Curl)).ToList();
        if (tabs.Count == 0)
        {
            return;
        }
        while (Panels.Count < tabs.Count)
        {
            Panels.Add(new ComparePanelModel());
        }
        for (var index = 0; index < tabs.Count; index++)
        {
            Panels[index].Name = tabs[index].Name;
            Panels[index].Input = tabs[index].Curl;
        }
        RefreshSearchScope();
    }

    private async void Compare_Click(object sender, RoutedEventArgs e)
    {
        CompareButton.IsEnabled = false;
        CompareProgress.IsActive = true;
        try
        {
            var inputs = Panels.Select(panel => panel.Input).ToList();
            var mode = (ModeCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "auto";
            var result = await Task.Run(() => ComputeDiff(inputs, mode));
            for (var index = 0; index < Panels.Count; index++)
            {
                Panels[index].DiffLines = result[index];
            }
            await RenderIncrementallyAsync();
            ApplySearch();
        }
        catch (Exception ex)
        {
            foreach (var panel in Panels)
            {
                panel.DiffLines = [$"ERROR: {ex.Message}"];
            }
            ApplySearch();
        }
        finally
        {
            CompareProgress.IsActive = false;
            CompareButton.IsEnabled = true;
        }
    }

    private async Task RenderIncrementallyAsync()
    {
        var largest = Panels.Count == 0 ? 0 : Panels.Max(panel => panel.DiffLines.Count);
        if (largest <= 20_000)
        {
            foreach (var panel in Panels)
            {
                panel.Output = string.Join(Environment.NewLine, panel.DiffLines);
            }
            return;
        }
        var builders = Panels.Select(_ => new System.Text.StringBuilder()).ToList();
        const int batchSize = 8000;
        for (var offset = 0; offset < largest; offset += batchSize)
        {
            for (var panelIndex = 0; panelIndex < Panels.Count; panelIndex++)
            {
                var lines = Panels[panelIndex].DiffLines;
                var end = Math.Min(lines.Count, offset + batchSize);
                for (var lineIndex = offset; lineIndex < end; lineIndex++)
                {
                    if (builders[panelIndex].Length > 0) builders[panelIndex].AppendLine();
                    builders[panelIndex].Append(lines[lineIndex]);
                }
                Panels[panelIndex].Output = builders[panelIndex].ToString();
            }
            await Task.Yield();
        }
    }

    private static List<List<string>> ComputeDiff(IReadOnlyList<string> inputs, string mode)
    {
        var effectiveMode = mode == "auto" ? DetectMode(inputs) : mode;
        var normalized = inputs.Select(input => Normalize(input, effectiveMode)).ToList();
        var rows = normalized.Count == 0 ? 0 : normalized.Max(lines => lines.Count);
        var output = normalized.Select(_ => new List<string>(rows)).ToList();
        for (var row = 0; row < rows; row++)
        {
            var values = normalized.Select(lines => row < lines.Count ? lines[row] : null).ToList();
            var allSame = values.Skip(1).All(value => value == values[0]);
            for (var panel = 0; panel < normalized.Count; panel++)
            {
                var value = values[panel];
                var marker = allSame ? " " : value is null ? "." : panel == 0 ? "-" : value == values[0] ? " " : "+";
                output[panel].Add(FormatLine(row, value, marker));
            }
        }
        return output;
    }

    private static string DetectMode(IReadOnlyList<string> inputs)
    {
        if (inputs.Count > 0 && inputs.All(input => input.TrimStart().StartsWith("curl ", StringComparison.OrdinalIgnoreCase)))
        {
            return "curl";
        }
        try
        {
            foreach (var input in inputs)
            {
                using var document = JsonDocument.Parse(input);
            }
            return "json";
        }
        catch
        {
            return "text";
        }
    }

    private static List<string> Normalize(string raw, string mode) => mode switch
    {
        "curl" => NormalizeCurl(raw),
        "json" => NormalizeJson(raw),
        "string" => NormalizeString(raw),
        _ => SplitLines(raw),
    };

    private static List<string> NormalizeCurl(string raw)
    {
        var request = CurlParser.Parse(raw);
        var lines = new List<string> { $"method = {request.Method}", $"url = {request.Url}" };
        lines.AddRange(request.Headers.OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(pair => $"header.{pair.Key.ToLowerInvariant()} = {pair.Value}"));
        if (!string.IsNullOrEmpty(request.Body))
        {
            try { lines.AddRange(NormalizeJson(request.Body).Select(line => "body." + line)); }
            catch { lines.AddRange(SplitLines(request.Body).Select(line => "body = " + line)); }
        }
        return lines;
    }

    private static List<string> NormalizeString(string raw)
    {
        try { return SplitLines(JsonSerializer.Deserialize<string>(raw) ?? ""); }
        catch { return SplitLines(raw.Replace("\\r\\n", "\n").Replace("\\n", "\n").Replace("\\t", "\t")); }
    }

    private static List<string> NormalizeJson(string raw)
    {
        using var document = JsonDocument.Parse(raw);
        var lines = new List<string>();
        Flatten(document.RootElement, "$", lines);
        return lines;
    }

    private static void Flatten(JsonElement element, string path, List<string> lines)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            foreach (var property in element.EnumerateObject().OrderBy(property => property.Name, StringComparer.Ordinal))
                Flatten(property.Value, $"{path}.{property.Name}", lines);
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            var index = 0;
            foreach (var item in element.EnumerateArray()) Flatten(item, $"{path}[{index++}]", lines);
        }
        else
        {
            lines.Add($"{path} = {element.GetRawText()}");
        }
    }

    private void RefreshSearchScope(ComparePanelModel? selected = null)
    {
        if (SearchScope is null)
        {
            return;
        }
        var selectedIndex = selected is null ? SearchScope.SelectedIndex : Panels.IndexOf(selected) + 1;
        SearchScope.ItemsSource = new[] { "All panels" }.Concat(Panels.Select(panel => panel.Name)).ToList();
        SearchScope.SelectedIndex = selectedIndex >= 0 && selectedIndex < SearchScope.Items.Count ? selectedIndex : 0;
    }

    private void PanelOutput_Loaded(object sender, RoutedEventArgs e)
    {
        if (sender is TextBox box && box.Tag is ComparePanelModel panel)
        {
            _outputBoxes[panel.Id] = box;
        }
    }

    private void PanelOutput_Unloaded(object sender, RoutedEventArgs e)
    {
        if (sender is TextBox box && box.Tag is ComparePanelModel panel)
        {
            _outputBoxes.Remove(panel.Id);
        }
    }

    private void SearchBox_TextChanged(object sender, TextChangedEventArgs e) => ApplySearch();
    private void SearchOption_Click(object sender, RoutedEventArgs e) => ApplySearch();
    private void SearchOption_Changed(object sender, SelectionChangedEventArgs e) => ApplySearch();

    private void ApplySearch()
    {
        if (!_isReady)
        {
            return;
        }
        var terms = SearchBox.Text.Split('|', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries);
        var scope = SearchScope.SelectedIndex - 1;
        for (var index = 0; index < Panels.Count; index++)
        {
            var filter = OnlyResultsCheck.IsChecked == true && (scope < 0 || scope == index);
            Panels[index].Output = string.Join(
                Environment.NewLine,
                !filter || terms.Length == 0
                    ? Panels[index].DiffLines
                    : Panels[index].DiffLines.Where(line => MatchesAny(line, terms)));
        }
        BuildMatches(terms, scope);
    }

    private void BuildMatches(string[] terms, int scope)
    {
        _matches.Clear();
        _matchIndex = -1;
        if (terms.Length == 0)
        {
            return;
        }
        for (var index = 0; index < Panels.Count; index++)
        {
            if ((scope < 0 || scope == index) && _outputBoxes.TryGetValue(Panels[index].Id, out var box))
            {
                AddMatches(box, terms);
            }
        }
        SelectMatch(1);
    }

    private void AddMatches(TextBox box, string[] terms)
    {
        foreach (var term in terms)
        {
            var offset = 0;
            while (offset <= box.Text.Length - term.Length && _matches.Count < 10000)
            {
                var hit = box.Text.IndexOf(term, offset,
                    CaseSensitiveCheck.IsChecked == true ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase);
                if (hit < 0) break;
                _matches.Add((box, hit, term.Length));
                offset = hit + Math.Max(1, term.Length);
            }
        }
        _matches.Sort((left, right) => left.Start.CompareTo(right.Start));
    }

    private bool MatchesAny(string text, string[] terms)
    {
        var comparison = CaseSensitiveCheck.IsChecked == true ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        return terms.Any(term => text.Contains(term, comparison));
    }

    private void PreviousMatch_Click(object sender, RoutedEventArgs e) => SelectMatch(-1);
    private void NextMatch_Click(object sender, RoutedEventArgs e) => SelectMatch(1);

    private void SelectMatch(int direction)
    {
        if (_matches.Count == 0) return;
        _matchIndex = (_matchIndex + direction + _matches.Count) % _matches.Count;
        var match = _matches[_matchIndex];
        match.Box.Focus(FocusState.Programmatic);
        match.Box.Select(match.Start, match.Length);
    }

    private static List<string> SplitLines(string text) => text.Replace("\r\n", "\n").Split('\n').ToList();
    private static string FormatLine(int index, string? value, string marker) => $"{index + 1,6} {marker} {value ?? ""}";
}
