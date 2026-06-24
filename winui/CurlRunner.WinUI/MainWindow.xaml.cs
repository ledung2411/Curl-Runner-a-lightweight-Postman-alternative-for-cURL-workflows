using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using CurlRunner.WinUI.Pages;

namespace CurlRunner.WinUI;

public sealed partial class MainWindow : Window
{
    public IntPtr WindowHandle => WinRT.Interop.WindowNative.GetWindowHandle(this);
    private readonly Dictionary<string, Type> _pages = new(StringComparer.OrdinalIgnoreCase)
    {
        ["requests"] = typeof(RequestsPage),
        ["library"] = typeof(LibraryPage),
        ["environments"] = typeof(EnvironmentsPage),
        ["scenarios"] = typeof(ScenariosPage),
        ["compare"] = typeof(ComparePage),
        ["converter"] = typeof(ConverterPage),
        ["ai"] = typeof(AiPage),
        ["settings"] = typeof(SettingsPage),
    };

    public MainWindow()
    {
        InitializeComponent();
        Title = "Curl Runner";
        ExtendsContentIntoTitleBar = true;
        SetTitleBar(AppTitleBar);
        SetTheme(AppServices.State.Settings.Theme switch
        {
            "light" => ElementTheme.Light,
            "dark" => ElementTheme.Dark,
            _ => ElementTheme.Default,
        });
        SetBackdrop(AppServices.State.Settings.MicaEnabled);
        AppServices.State.EnvironmentsChanged += State_EnvironmentsChanged;
        RefreshEnvironmentSelector();
        RootNavigation.SelectedItem = RootNavigation.MenuItems[0];
        Navigate("requests", "Requests");
    }

    private void AppTitleBar_PaneToggleRequested(TitleBar sender, object args)
    {
        RootNavigation.IsPaneOpen = !RootNavigation.IsPaneOpen;
    }

    private void RootNavigation_SelectionChanged(
        NavigationView sender,
        NavigationViewSelectionChangedEventArgs args)
    {
        if (args.IsSettingsSelected)
        {
            Navigate("settings", "Settings");
            return;
        }
        if (args.SelectedItemContainer?.Tag is string tag)
        {
            Navigate(tag, args.SelectedItemContainer.Content?.ToString() ?? "Curl Runner");
        }
    }

    private void Navigate(string key, string title)
    {
        if (!_pages.TryGetValue(key, out var pageType))
        {
            return;
        }
        if (ContentFrame.CurrentSourcePageType != pageType)
        {
            ContentFrame.Navigate(pageType);
        }
        AppTitleBar.Subtitle = title;
    }

    public void NavigateTo(string key)
    {
        var item = RootNavigation.MenuItems
            .OfType<NavigationViewItem>()
            .FirstOrDefault(candidate => string.Equals(candidate.Tag?.ToString(), key, StringComparison.OrdinalIgnoreCase));
        if (item is not null)
        {
            RootNavigation.SelectedItem = item;
        }
        Navigate(key, item?.Content?.ToString() ?? key);
    }

    private void State_EnvironmentsChanged(object? sender, EventArgs e) => RefreshEnvironmentSelector();

    private void RefreshEnvironmentSelector()
    {
        var names = AppServices.State.Environments.Keys
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
        EnvironmentCombo.ItemsSource = names;
        EnvironmentCombo.SelectedItem = AppServices.State.ActiveEnvironment;
    }

    private void EnvironmentCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (EnvironmentCombo.SelectedItem is string name)
        {
            AppServices.State.SetActiveEnvironment(name);
        }
    }

    private void GlobalSearchBox_TextChanged(AutoSuggestBox sender, AutoSuggestBoxTextChangedEventArgs args)
    {
        if (args.Reason != AutoSuggestionBoxTextChangeReason.UserInput)
        {
            return;
        }
        var query = sender.Text.Trim();
        var routes = _pages.Keys
            .Where(key => key.Contains(query, StringComparison.OrdinalIgnoreCase))
            .Select(key => char.ToUpperInvariant(key[0]) + key[1..])
            .ToList();
        var history = AppServices.State.History
            .Where(item => item.Method.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                           item.Url.Contains(query, StringComparison.OrdinalIgnoreCase))
            .Take(8)
            .Select(item => $"{item.Method}  {item.Url}");
        var scenarios = AppServices.State.Scenarios
            .Where(item => item.Name.Contains(query, StringComparison.OrdinalIgnoreCase))
            .Take(6)
            .Select(item => $"Scenario  {item.Name}");
        sender.ItemsSource = routes.Concat(scenarios).Concat(history).Take(12).ToList();
    }

    private void GlobalSearchBox_QuerySubmitted(AutoSuggestBox sender, AutoSuggestBoxQuerySubmittedEventArgs args)
    {
        var query = (args.ChosenSuggestion?.ToString() ?? args.QueryText).Trim().ToLowerInvariant();
        var key = _pages.Keys.FirstOrDefault(candidate =>
            candidate.Contains(query, StringComparison.OrdinalIgnoreCase) ||
            query.Contains(candidate, StringComparison.OrdinalIgnoreCase));
        if (key is not null)
        {
            NavigateTo(key);
            return;
        }
        var history = AppServices.State.History.FirstOrDefault(item =>
            query.Contains(item.Url, StringComparison.OrdinalIgnoreCase) ||
            string.Equals($"{item.Method}  {item.Url}", query, StringComparison.OrdinalIgnoreCase));
        if (history is not null)
        {
            AppServices.Workspace.RequestOpen(history.Method, history.Curl, newTab: true);
            NavigateTo("requests");
            return;
        }
        var scenario = AppServices.State.Scenarios.FirstOrDefault(item =>
            string.Equals($"scenario  {item.Name}", query, StringComparison.OrdinalIgnoreCase) ||
            string.Equals(item.Name, query, StringComparison.OrdinalIgnoreCase));
        if (scenario is not null)
        {
            NavigateTo("scenarios");
        }
    }

    public void SetTheme(ElementTheme theme)
    {
        RootGrid.RequestedTheme = theme;
    }

    public void SetBackdrop(bool enabled)
    {
        SystemBackdrop = enabled ? new MicaBackdrop() : null;
    }
}
