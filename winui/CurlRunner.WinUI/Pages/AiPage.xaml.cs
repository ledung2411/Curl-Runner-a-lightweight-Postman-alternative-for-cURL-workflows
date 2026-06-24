using CurlRunner.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.System;

namespace CurlRunner.WinUI.Pages;

public sealed partial class AiPage : Page
{
    private readonly AiAnalysisService _ai = new();
    private CancellationTokenSource? _operation;
    private string _apiKey = "";
    private bool _ready;

    public AiPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
    }

    private async void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (!_ready)
        {
            var settings = AppServices.State.Settings;
            LocalRadio.IsChecked = settings.AiProvider != "openai";
            BillingRadio.IsChecked = settings.AiProvider == "openai";
            ModelBox.Text = settings.AiProvider == "openai" ? settings.OpenAiModel : settings.OllamaModel;
            _ready = true;
        }
        RefreshResponseContext();
        await RefreshOllamaStatusAsync();
    }

    private void RefreshResponseContext()
    {
        var tab = AppServices.Workspace.ActiveTab;
        ResponseContextText.Text = tab?.Response is null
            ? "No response is available. Send a request first."
            : $"{tab.Name} | {tab.Method} {tab.Url} | {tab.Response.StatusCode} {tab.Response.Reason}";
        AnalysisBox.Text = tab?.AiAnalysis ?? "";
    }

    private async void Provider_Changed(object sender, RoutedEventArgs e)
    {
        if (!_ready)
        {
            return;
        }
        var settings = AppServices.State.Settings;
        settings.AiProvider = BillingRadio.IsChecked == true ? "openai" : "ollama";
        ModelBox.Text = settings.AiProvider == "openai" ? settings.OpenAiModel : settings.OllamaModel;
        await AppServices.State.SaveSettingsAsync();
    }

    private async void RefreshStatus_Click(object sender, RoutedEventArgs e) => await RefreshOllamaStatusAsync();

    private async Task RefreshOllamaStatusAsync()
    {
        ProviderProgress.IsActive = true;
        try
        {
            var settings = AppServices.State.Settings;
            var status = await _ai.GetOllamaStatusAsync(settings.OllamaBaseUrl, settings.OllamaModel);
            CliStatusText.Text = $"CLI: {(status.CliInstalled ? "installed" : "not installed")}";
            ServerStatusText.Text = $"Server: {(status.ServerRunning ? "running" : "not reachable")}";
            ModelStatusText.Text = status.Models.Count == 0
                ? $"Model: {settings.OllamaModel} is not installed"
                : $"Models: {string.Join(", ", status.Models)}";
            InstallButton.IsEnabled = !status.CliInstalled;
            StartButton.IsEnabled = status.CliInstalled && !status.ServerRunning;
            PullButton.IsEnabled = status.ServerRunning && status.SelectedModel is null;
        }
        finally
        {
            ProviderProgress.IsActive = false;
        }
    }

    private async void Analyze_Click(object sender, RoutedEventArgs e)
    {
        var tab = AppServices.Workspace.ActiveTab;
        if (tab?.Response is null)
        {
            ShowMessage("Send a request before running AI analysis.", InfoBarSeverity.Warning);
            return;
        }
        AnalyzeButton.IsEnabled = false;
        ProviderProgress.IsActive = true;
        _operation = new CancellationTokenSource();
        try
        {
            var context = _ai.BuildContext(tab);
            string analysis;
            if (BillingRadio.IsChecked == true)
            {
                var key = await ResolveApiKeyAsync();
                if (key is null)
                {
                    return;
                }
                var model = string.IsNullOrWhiteSpace(ModelBox.Text) ? "gpt-5.4-mini" : ModelBox.Text.Trim();
                AppServices.State.Settings.OpenAiModel = model;
                analysis = await _ai.AnalyzeWithOpenAiAsync(context, key, model, _operation.Token);
            }
            else
            {
                var settings = AppServices.State.Settings;
                var model = string.IsNullOrWhiteSpace(ModelBox.Text) ? "llama3.2" : ModelBox.Text.Trim();
                settings.OllamaModel = model;
                var result = await _ai.AnalyzeWithOllamaAsync(context, settings.OllamaBaseUrl, model, _operation.Token);
                analysis = $"Model: {result.Model}{Environment.NewLine}{Environment.NewLine}{result.Analysis}";
            }
            await AppServices.State.SaveSettingsAsync();
            tab.AiAnalysis = analysis;
            AnalysisBox.Text = analysis;
            AppServices.Workspace.PublishTabs(AppServices.Workspace.OpenTabs, tab);
            ShowMessage("Analysis completed.", InfoBarSeverity.Success);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            ShowMessage(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            _operation?.Dispose();
            _operation = null;
            ProviderProgress.IsActive = false;
            AnalyzeButton.IsEnabled = true;
        }
    }

    private async Task<string?> ResolveApiKeyAsync()
    {
        if (!string.IsNullOrWhiteSpace(_apiKey))
        {
            return _apiKey;
        }
        var environmentKey = Environment.GetEnvironmentVariable("OPENAI_API_KEY");
        if (!string.IsNullOrWhiteSpace(environmentKey))
        {
            return environmentKey;
        }
        var input = new PasswordBox { PlaceholderText = "sk-..." };
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "OpenAI API key",
            Content = input,
            PrimaryButtonText = "Use for this session",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary || string.IsNullOrWhiteSpace(input.Password))
        {
            return null;
        }
        _apiKey = input.Password.Trim();
        return _apiKey;
    }

    private async void Install_Click(object sender, RoutedEventArgs e)
    {
        await RunSetupOperationAsync("Installing Ollama with winget...", token =>
            _ai.InstallOllamaAsync(AppendLog, token));
    }

    private async void Start_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            AppendLog("Starting Ollama server...");
            _ai.StartOllama();
            await Task.Delay(2000);
            await RefreshOllamaStatusAsync();
        }
        catch (Exception ex)
        {
            ShowMessage(ex.Message, InfoBarSeverity.Error);
        }
    }

    private async void Pull_Click(object sender, RoutedEventArgs e)
    {
        var model = string.IsNullOrWhiteSpace(ModelBox.Text) ? "llama3.2" : ModelBox.Text.Trim();
        await RunSetupOperationAsync($"Pulling {model}...", token =>
            _ai.PullModelAsync(model, AppendLog, token));
    }

    private async Task RunSetupOperationAsync(string title, Func<CancellationToken, Task<int>> operation)
    {
        AppendLog(title);
        SetSetupBusy(true);
        _operation = new CancellationTokenSource();
        try
        {
            var exitCode = await operation(_operation.Token);
            AppendLog($"Completed with exit code {exitCode}.");
            await RefreshOllamaStatusAsync();
            if (exitCode != 0)
            {
                ShowMessage($"Setup command failed with exit code {exitCode}.", InfoBarSeverity.Error);
            }
        }
        catch (Exception ex)
        {
            AppendLog(ex.Message);
            ShowMessage(ex.Message, InfoBarSeverity.Error);
        }
        finally
        {
            _operation?.Dispose();
            _operation = null;
            SetSetupBusy(false);
        }
    }

    private async void OpenDownload_Click(object sender, RoutedEventArgs e) =>
        await Launcher.LaunchUriAsync(new Uri("https://ollama.com/download/windows"));

    private void AppendLog(string message) => DispatcherQueue.TryEnqueue(() =>
    {
        SetupLogBox.Text += (SetupLogBox.Text.Length == 0 ? "" : Environment.NewLine) + message;
    });

    private void SetSetupBusy(bool busy)
    {
        ProviderProgress.IsActive = busy;
        InstallButton.IsEnabled = !busy;
        StartButton.IsEnabled = !busy;
        PullButton.IsEnabled = !busy;
    }

    private void ShowMessage(string message, InfoBarSeverity severity)
    {
        AiInfoBar.Message = message;
        AiInfoBar.Severity = severity;
        AiInfoBar.IsOpen = true;
    }
}
