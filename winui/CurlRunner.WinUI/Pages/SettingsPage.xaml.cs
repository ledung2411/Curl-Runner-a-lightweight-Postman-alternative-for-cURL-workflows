using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace CurlRunner.WinUI.Pages;

public sealed partial class SettingsPage : Page
{
    private bool _loaded;

    public SettingsPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
    }

    private void Page_Loaded(object sender, RoutedEventArgs e)
    {
        var settings = AppServices.State.Settings;
        ThemeCombo.SelectedIndex = settings.Theme switch { "light" => 1, "dark" => 2, _ => 0 };
        MicaToggle.IsOn = settings.MicaEnabled;
        VerifySslDefaultToggle.IsOn = settings.DefaultVerifySsl;
        RedirectDefaultToggle.IsOn = settings.DefaultFollowRedirects;
        AutoDecodeDefaultToggle.IsOn = settings.DefaultAutoDecode;
        TimeoutDefaultBox.Value = settings.DefaultTimeoutSeconds;
        _loaded = true;
    }

    private void ThemeCombo_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        var tag = (ThemeCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString();
        var theme = tag switch
        {
            "light" => ElementTheme.Light,
            "dark" => ElementTheme.Dark,
            _ => ElementTheme.Default,
        };
        App.MainWindowInstance?.SetTheme(theme);
        if (_loaded)
        {
            AppServices.State.Settings.Theme = tag == "default" ? "system" : tag ?? "system";
        }
    }

    private void MicaToggle_Toggled(object sender, RoutedEventArgs e)
    {
        App.MainWindowInstance?.SetBackdrop(MicaToggle.IsOn);
        if (_loaded)
        {
            AppServices.State.Settings.MicaEnabled = MicaToggle.IsOn;
        }
    }

    private async void SaveSettings_Click(object sender, RoutedEventArgs e)
    {
        var settings = AppServices.State.Settings;
        settings.DefaultVerifySsl = VerifySslDefaultToggle.IsOn;
        settings.DefaultFollowRedirects = RedirectDefaultToggle.IsOn;
        settings.DefaultAutoDecode = AutoDecodeDefaultToggle.IsOn;
        settings.DefaultTimeoutSeconds = (int)Math.Clamp(TimeoutDefaultBox.Value, 1, 3600);
        await AppServices.State.SaveSettingsAsync();
        SettingsInfoBar.Message = "Settings saved.";
        SettingsInfoBar.Severity = InfoBarSeverity.Success;
        SettingsInfoBar.IsOpen = true;
    }
}
