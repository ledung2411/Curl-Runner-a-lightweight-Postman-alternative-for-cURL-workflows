using CurlRunner.WinUI.Models;
using CurlRunner.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Collections.ObjectModel;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace CurlRunner.WinUI.Pages;

public sealed partial class ScenariosPage : Page
{
    private readonly ApiClientService _apiClient = new();
    private List<ScenarioDefinition> _scenarios = [];
    private readonly Dictionary<string, ScenarioStepResult> _lastResults = new(StringComparer.OrdinalIgnoreCase);
    private CancellationTokenSource? _runCancellation;
    private string? _selectedStepId;
    private bool _changingSelection;
    private bool _loaded;

    public ObservableCollection<ScenarioStepRow> StepRows { get; } = [];

    public ScenariosPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (_loaded)
        {
            return;
        }
        _loaded = true;
        await LoadScenariosAsync();
    }

    private async Task LoadScenariosAsync()
    {
        _scenarios = AppServices.State.Scenarios;
        EnsureIds();
        ScenarioList.ItemsSource = _scenarios;
        if (_scenarios.Count > 0)
        {
            ScenarioList.SelectedIndex = 0;
        }
        else
        {
            ClearStepEditor();
            RefreshSteps();
        }
    }

    private void EnsureIds()
    {
        foreach (var scenario in _scenarios)
        {
            if (string.IsNullOrWhiteSpace(scenario.Id)) scenario.Id = NewId();
            foreach (var step in scenario.Steps)
            {
                if (string.IsNullOrWhiteSpace(step.Id)) step.Id = NewId();
            }
        }
    }

    private ScenarioDefinition? CurrentScenario => ScenarioList.SelectedItem as ScenarioDefinition;
    private ScenarioStepDefinition? SelectedStep => CurrentScenario?.Steps.FirstOrDefault(step => step.Id == _selectedStepId);

    private void ScenarioList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_changingSelection)
        {
            return;
        }
        SaveSelectedStepFromEditor(showError: false);
        _selectedStepId = null;
        _lastResults.Clear();
        ExportButton.IsEnabled = false;
        RunLogBox.Text = "";
        RefreshSteps();
        ClearStepEditor();
    }

    private async void NewScenario_Click(object sender, RoutedEventArgs e)
    {
        var name = await PromptAsync("New scenario", "Scenario name", "New Scenario");
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }
        var scenario = new ScenarioDefinition { Id = NewId(), Name = name };
        _scenarios.Add(scenario);
        ScenarioList.ItemsSource = null;
        ScenarioList.ItemsSource = _scenarios;
        ScenarioList.SelectedItem = scenario;
        await SaveAllAsync();
    }

    private async void RenameScenario_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario)
        {
            return;
        }
        var name = await PromptAsync("Rename scenario", "Scenario name", scenario.Name);
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }
        scenario.Name = name;
        ScenarioList.ItemsSource = null;
        ScenarioList.ItemsSource = _scenarios;
        ScenarioList.SelectedItem = scenario;
        await SaveAllAsync();
    }

    private async void DeleteScenario_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario ||
            !await ConfirmAsync("Delete scenario?", $"Delete {scenario.Name} and all of its steps?"))
        {
            return;
        }
        _scenarios.Remove(scenario);
        ScenarioList.ItemsSource = null;
        ScenarioList.ItemsSource = _scenarios;
        if (_scenarios.Count > 0) ScenarioList.SelectedIndex = 0;
        await SaveAllAsync();
    }

    private async void SaveScenario_Click(object sender, RoutedEventArgs e)
    {
        if (!SaveSelectedStepFromEditor(showError: true))
        {
            return;
        }
        await SaveAllAsync();
        RefreshSteps(_selectedStepId);
        ShowMessage("Scenario saved.", InfoBarSeverity.Success);
    }

    private async Task SaveAllAsync() => await AppServices.State.SaveScenariosAsync();

    private void AddStep_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario)
        {
            ShowMessage("Create or select a scenario first.", InfoBarSeverity.Warning);
            return;
        }
        SaveSelectedStepFromEditor(showError: false);
        var step = new ScenarioStepDefinition
        {
            Id = NewId(),
            Name = "New Step",
            Group = scenario.Steps.Count == 0 ? 1 : scenario.Steps.Max(item => item.Group) + 1,
        };
        scenario.Steps.Add(step);
        _selectedStepId = step.Id;
        RefreshSteps(step.Id);
        LoadStepEditor(step);
    }

    private void DuplicateStep_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario || SelectedStep is not ScenarioStepDefinition source)
        {
            return;
        }
        SaveSelectedStepFromEditor(showError: false);
        var step = new ScenarioStepDefinition
        {
            Id = NewId(), Name = source.Name + " Copy", Curl = source.Curl, Group = source.Group,
            Enabled = source.Enabled, Extractors = source.Extractors, Assertions = source.Assertions,
        };
        scenario.Steps.Insert(scenario.Steps.IndexOf(source) + 1, step);
        _selectedStepId = step.Id;
        RefreshSteps(step.Id);
        LoadStepEditor(step);
    }

    private void DeleteStep_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario || SelectedStep is not ScenarioStepDefinition step)
        {
            return;
        }
        scenario.Steps.Remove(step);
        _selectedStepId = null;
        RefreshSteps();
        ClearStepEditor();
    }

    private void MoveStepUp_Click(object sender, RoutedEventArgs e) => MoveStep(-1);
    private void MoveStepDown_Click(object sender, RoutedEventArgs e) => MoveStep(1);

    private void MoveStep(int direction)
    {
        if (CurrentScenario is not ScenarioDefinition scenario || SelectedStep is not ScenarioStepDefinition step)
        {
            return;
        }
        var index = scenario.Steps.IndexOf(step);
        var target = index + direction;
        if (target < 0 || target >= scenario.Steps.Count)
        {
            return;
        }
        (scenario.Steps[index], scenario.Steps[target]) = (scenario.Steps[target], scenario.Steps[index]);
        RefreshSteps(step.Id);
    }

    private void StepList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_changingSelection || StepList.SelectedItem is not ScenarioStepRow row)
        {
            return;
        }
        SaveSelectedStepFromEditor(showError: false);
        _selectedStepId = row.Definition.Id;
        LoadStepEditor(row.Definition);
    }

    private void LoadStepEditor(ScenarioStepDefinition step)
    {
        StepNameBox.Text = step.Name;
        StepGroupBox.Value = Math.Max(1, step.Group);
        StepEnabledCheck.IsChecked = step.Enabled;
        StepCurlBox.Text = step.Curl;
        ExtractorsBox.Text = step.Extractors;
        AssertionsBox.Text = step.Assertions;
    }

    private void ClearStepEditor()
    {
        StepNameBox.Text = "";
        StepGroupBox.Value = 1;
        StepEnabledCheck.IsChecked = true;
        StepCurlBox.Text = "";
        ExtractorsBox.Text = "";
        AssertionsBox.Text = "";
    }

    private void UpdateStep_Click(object sender, RoutedEventArgs e)
    {
        if (SaveSelectedStepFromEditor(showError: true))
        {
            RefreshSteps(_selectedStepId);
        }
    }

    private bool SaveSelectedStepFromEditor(bool showError)
    {
        if (SelectedStep is not ScenarioStepDefinition step)
        {
            return true;
        }
        var group = double.IsNaN(StepGroupBox.Value) ? 1 : (int)StepGroupBox.Value;
        if (group < 1)
        {
            if (showError) ShowMessage("Group must be an integer greater than zero.", InfoBarSeverity.Error);
            return false;
        }
        step.Name = string.IsNullOrWhiteSpace(StepNameBox.Text) ? "Unnamed Step" : StepNameBox.Text.Trim();
        step.Group = group;
        step.Enabled = StepEnabledCheck.IsChecked == true;
        step.Curl = StepCurlBox.Text.Trim();
        step.Extractors = ExtractorsBox.Text.Trim();
        step.Assertions = AssertionsBox.Text.Trim();
        return true;
    }

    private void RefreshSteps(string? selectId = null)
    {
        StepRows.Clear();
        var scenario = CurrentScenario;
        if (scenario is null)
        {
            SummaryText.Text = "No scenario selected";
            return;
        }
        for (var index = 0; index < scenario.Steps.Count; index++)
        {
            var step = scenario.Steps[index];
            var preview = PreviewRequest(step.Curl);
            _lastResults.TryGetValue(step.Id, out var result);
            StepRows.Add(new ScenarioStepRow
            {
                Definition = step,
                Order = index + 1,
                Method = preview.Method,
                Url = preview.Url,
                Status = !step.Enabled ? "Disabled" : result is null ? "Not run" : result.Passed ? "Passed" : "Failed",
                Elapsed = result is null ? "" : $"{result.ElapsedMilliseconds} ms",
                Result = result,
            });
        }
        SummaryText.Text = $"{scenario.Steps.Count} steps | same group runs in parallel";
        if (selectId is not null)
        {
            _changingSelection = true;
            StepList.SelectedItem = StepRows.FirstOrDefault(row => row.Definition.Id == selectId);
            _changingSelection = false;
        }
    }

    private async void ImportTabs_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario)
        {
            ShowMessage("Create or select a scenario first.", InfoBarSeverity.Warning);
            return;
        }
        SaveSelectedStepFromEditor(showError: false);
        var group = scenario.Steps.Count == 0 ? 1 : scenario.Steps.Max(step => step.Group) + 1;
        var added = 0;
        foreach (var tab in AppServices.Workspace.OpenTabs.Where(tab => !string.IsNullOrWhiteSpace(tab.Curl)))
        {
            scenario.Steps.Add(new ScenarioStepDefinition
            {
                Id = NewId(), Name = tab.Name, Curl = tab.Curl, Group = group++, Enabled = true,
            });
            added++;
        }
        await SaveAllAsync();
        RefreshSteps();
        ShowMessage($"Imported {added} open request tab(s).", added > 0 ? InfoBarSeverity.Success : InfoBarSeverity.Informational);
    }

    private async void Run_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario)
        {
            return;
        }
        if (!SaveSelectedStepFromEditor(showError: true))
        {
            return;
        }
        await SaveAllAsync();
        _lastResults.Clear();
        RunLogBox.Text = "";
        foreach (var step in scenario.Steps.Where(step => !step.Enabled))
        {
            _lastResults[step.Id] = new ScenarioStepResult { Skipped = true };
        }
        RefreshSteps(_selectedStepId);
        SetRunning(true);
        _runCancellation = new CancellationTokenSource();
        var runtimeEnvironment = new Dictionary<string, string>(AppServices.State.ActiveVariables, StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (var group in scenario.Steps.Where(step => step.Enabled).GroupBy(step => Math.Max(1, step.Group)).OrderBy(group => group.Key))
            {
                _runCancellation.Token.ThrowIfCancellationRequested();
                AppendLog($"Group {group.Key}: running {group.Count()} step(s) in parallel.");
                var rows = group.Select(step => StepRows.First(row => row.Definition.Id == step.Id)).ToList();
                foreach (var row in rows) row.Status = "Running";
                var snapshot = new Dictionary<string, string>(runtimeEnvironment, StringComparer.OrdinalIgnoreCase);
                var results = await Task.WhenAll(rows.Select(row => RunStepAsync(row, snapshot, _runCancellation.Token)));
                foreach (var result in results.Where(result => result.Passed))
                {
                    foreach (var pair in result.ExtractedValues) runtimeEnvironment[pair.Key] = pair.Value;
                }
                if (results.Any(result => !result.Passed) && StopOnFailButton.IsChecked == true)
                {
                    AppendLog($"Group {group.Key} failed. Remaining groups skipped.");
                    break;
                }
            }
            var passed = _lastResults.Values.Count(result => result.Passed);
            var failed = _lastResults.Values.Count(result => !result.Passed && !result.Skipped);
            var skipped = scenario.Steps.Count - passed - failed;
            SummaryText.Text = $"Passed {passed} | Failed {failed} | Skipped {skipped}";
            AppendLog($"Scenario complete: {passed} passed, {failed} failed, {skipped} skipped.");
            ShowMessage("Scenario completed.", failed == 0 ? InfoBarSeverity.Success : InfoBarSeverity.Error);
            ExportButton.IsEnabled = true;
        }
        catch (OperationCanceledException)
        {
            AppendLog("Scenario stopped.");
            ShowMessage("Scenario stopped.", InfoBarSeverity.Warning);
            ExportButton.IsEnabled = _lastResults.Count > 0;
        }
        finally
        {
            _runCancellation.Dispose();
            _runCancellation = null;
            SetRunning(false);
        }
    }

    private async Task<ScenarioStepResult> RunStepAsync(
        ScenarioStepRow row,
        IReadOnlyDictionary<string, string> environment,
        CancellationToken cancellationToken)
    {
        ScenarioStepResult result;
        try
        {
            var definition = CurlParser.Parse(EnvironmentService.Apply(row.Definition.Curl, environment));
            definition.AutoDecode = true;
            var response = await _apiClient.SendAsync(definition, cancellationToken);
            var extracts = ScenarioRuleService.Extract(row.Definition.Extractors, response);
            var assertions = ScenarioRuleService.Assert(row.Definition.Assertions, response);
            result = new ScenarioStepResult
            {
                Passed = assertions.Passed,
                StatusCode = response.StatusCode,
                Reason = response.Reason,
                ElapsedMilliseconds = response.ElapsedMilliseconds,
                Method = definition.Method,
                Url = definition.Url,
                AssertionDetails = assertions.Details,
                ExtractDetails = extracts.Details,
                ExtractedValues = extracts.Values,
            };
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            result = new ScenarioStepResult { Passed = false, Error = ex.Message, Method = row.Method, Url = row.Url };
        }
        _lastResults[row.Definition.Id] = result;
        row.Result = result;
        row.Status = result.Passed ? $"Passed {result.StatusCode}" : result.StatusCode > 0 ? $"Failed {result.StatusCode}" : "Error";
        row.Elapsed = result.ElapsedMilliseconds > 0 ? $"{result.ElapsedMilliseconds} ms" : "";
        var details = string.Join("; ", result.AssertionDetails.Concat(result.ExtractDetails));
        AppendLog($"{row.Name}: {row.Status}{(details.Length > 0 ? " | " + details : "")}{(result.Error.Length > 0 ? " | " + result.Error : "")}");
        return result;
    }

    private void Stop_Click(object sender, RoutedEventArgs e) => _runCancellation?.Cancel();

    private void SetRunning(bool running)
    {
        RunButton.IsEnabled = !running;
        StopButton.IsEnabled = running;
        ScenarioList.IsEnabled = !running;
        StepList.IsEnabled = !running;
    }

    private async void ExportReport_Click(object sender, RoutedEventArgs e)
    {
        if (CurrentScenario is not ScenarioDefinition scenario || sender is not MenuFlyoutItem item)
        {
            return;
        }
        var extension = item.Tag?.ToString() ?? "html";
        var picker = new FileSavePicker { SuggestedFileName = SanitizeFilename(scenario.Name) + "-report" };
        if (extension == "html") picker.FileTypeChoices.Add("HTML report", [".html"]);
        else if (extension == "csv") picker.FileTypeChoices.Add("CSV results", [".csv"]);
        else picker.FileTypeChoices.Add("JUnit XML", [".xml"]);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
        var file = await picker.PickSaveFileAsync();
        if (file is null)
        {
            return;
        }
        var content = extension switch
        {
            "csv" => ScenarioReportService.BuildCsv(scenario, _lastResults),
            "xml" => ScenarioReportService.BuildJUnit(scenario, _lastResults),
            _ => ScenarioReportService.BuildHtml(scenario, AppServices.State.ActiveEnvironment, _lastResults),
        };
        await FileIO.WriteTextAsync(file, content, Windows.Storage.Streams.UnicodeEncoding.Utf8);
        ShowMessage($"Report saved: {file.Name}", InfoBarSeverity.Success);
    }

    private static ApiRequestDefinition PreviewRequest(string curl)
    {
        try { return CurlParser.Parse(curl); }
        catch { return new ApiRequestDefinition { Method = "", Url = string.IsNullOrWhiteSpace(curl) ? "" : curl.Trim() }; }
    }

    private void AppendLog(string message)
    {
        RunLogBox.Text += (RunLogBox.Text.Length == 0 ? "" : Environment.NewLine) + message;
    }

    private async Task<string?> PromptAsync(string title, string placeholder, string value)
    {
        var input = new TextBox { PlaceholderText = placeholder, Text = value };
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot, Title = title, Content = input, PrimaryButtonText = "Save",
            CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Primary,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary ? input.Text.Trim() : null;
    }

    private async Task<bool> ConfirmAsync(string title, string message)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot, Title = title, Content = message, PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.Close,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }

    private void ShowMessage(string message, InfoBarSeverity severity)
    {
        ScenarioInfoBar.Message = message;
        ScenarioInfoBar.Severity = severity;
        ScenarioInfoBar.IsOpen = true;
    }

    private static string NewId() => Guid.NewGuid().ToString("N")[..8];
    private static string SanitizeFilename(string value) => string.Concat(value.Select(ch => Path.GetInvalidFileNameChars().Contains(ch) ? '_' : ch));
}
