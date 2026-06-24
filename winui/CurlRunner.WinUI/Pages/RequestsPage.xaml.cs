using CurlRunner.WinUI.Models;
using CurlRunner.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Text.Json;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace CurlRunner.WinUI.Pages;

public sealed partial class RequestsPage : Page
{
    private readonly ApiClientService _apiClient = new();
    private readonly List<RequestTabSession> _tabs = [];
    private RequestTabSession? _activeTab;
    private CancellationTokenSource? _requestCancellation;
    private int _searchIndex = -1;
    private bool _loadingTab;
    private bool _loaded;

    public ObservableCollection<HeaderEntry> HeaderRows { get; } = [];

    public RequestsPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
        AppServices.Workspace.OpenRequestRequested += Workspace_OpenRequestRequested;
        AppServices.State.EnvironmentsChanged += (_, _) => DispatcherQueue.TryEnqueue(UpdateEnvironmentHint);
    }

    private void Page_Loaded(object sender, RoutedEventArgs e)
    {
        if (!_loaded)
        {
            _loaded = true;
            AddTab("Request 1", "");
        }
        var pending = AppServices.Workspace.TakePendingOpenRequest();
        if (pending is not null)
        {
            OpenRequest(pending);
        }
    }

    private void Workspace_OpenRequestRequested(object? sender, OpenRequestEventArgs e)
    {
        DispatcherQueue.TryEnqueue(() =>
        {
            var pending = AppServices.Workspace.TakePendingOpenRequest() ?? e;
            OpenRequest(pending);
        });
    }

    private void OpenRequest(OpenRequestEventArgs request)
    {
        if (request.NewTab || _activeTab is null)
        {
            AddTab(request.Name, request.Curl);
        }
        else
        {
            CurlBox.Text = request.Curl;
            _activeTab.Name = request.Name;
            ActiveTabViewItem()!.Header = request.Name;
            ParseCurlIntoEditor();
            SaveActiveTab();
        }
    }

    private void AddTab(string? name = null, string curl = "")
    {
        SaveActiveTab();
        var settings = AppServices.State.Settings;
        var tab = new RequestTabSession
        {
            Name = string.IsNullOrWhiteSpace(name) ? $"Request {_tabs.Count + 1}" : name,
            Curl = curl,
            TimeoutSeconds = settings.DefaultTimeoutSeconds,
            VerifySsl = settings.DefaultVerifySsl,
            FollowRedirects = settings.DefaultFollowRedirects,
            AutoDecode = settings.DefaultAutoDecode,
        };
        _tabs.Add(tab);
        var item = new TabViewItem { Header = tab.Name, Tag = tab, IsClosable = true };
        RequestTabs.TabItems.Add(item);
        RequestTabs.SelectedItem = item;
        if (!string.IsNullOrWhiteSpace(curl))
        {
            ParseCurlIntoEditor();
        }
        PublishWorkspace();
    }

    private void RequestTabs_AddTabButtonClick(TabView sender, object args) => AddTab();

    private void RequestTabs_TabCloseRequested(TabView sender, TabViewTabCloseRequestedEventArgs args)
    {
        if (args.Item is not TabViewItem item || item.Tag is not RequestTabSession tab)
        {
            return;
        }
        if (ReferenceEquals(tab, _activeTab))
        {
            SaveActiveTab();
        }
        var index = RequestTabs.TabItems.IndexOf(item);
        RequestTabs.TabItems.Remove(item);
        _tabs.Remove(tab);
        if (_tabs.Count == 0)
        {
            AddTab();
        }
        else
        {
            RequestTabs.SelectedIndex = Math.Min(index, _tabs.Count - 1);
        }
        PublishWorkspace();
    }

    private void RequestTabs_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (_loadingTab || RequestTabs.SelectedItem is not TabViewItem item || item.Tag is not RequestTabSession tab)
        {
            return;
        }
        SaveActiveTab();
        _activeTab = tab;
        LoadTab(tab);
        PublishWorkspace();
    }

    private async void RenameTab_Click(object sender, RoutedEventArgs e)
    {
        if (_activeTab is null)
        {
            return;
        }
        var input = new TextBox { Text = _activeTab.Name, PlaceholderText = "Request name" };
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Rename request tab",
            Content = input,
            PrimaryButtonText = "Rename",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary || string.IsNullOrWhiteSpace(input.Text))
        {
            return;
        }
        _activeTab.Name = input.Text.Trim();
        ActiveTabViewItem()!.Header = _activeTab.Name;
        PublishWorkspace();
    }

    private TabViewItem? ActiveTabViewItem() => RequestTabs.SelectedItem as TabViewItem;

    private void LoadTab(RequestTabSession tab)
    {
        _loadingTab = true;
        try
        {
            CurlBox.Text = tab.Curl;
            SelectMethod(tab.Method);
            UrlBox.Text = tab.Url;
            BodyBox.Text = tab.Body;
            PreRequestBox.Text = tab.PreRequestScript;
            VerifySslToggle.IsOn = tab.VerifySsl;
            RedirectToggle.IsOn = tab.FollowRedirects;
            AutoDecodeToggle.IsOn = tab.AutoDecode;
            TimeoutBox.Value = tab.TimeoutSeconds;
            RepeatBox.Value = tab.Repeat;
            SetHeaderRows(tab.Headers);
            DisplayResponse(tab);
            UpdateEnvironmentHint();
        }
        finally
        {
            _loadingTab = false;
        }
    }

    private void SaveActiveTab()
    {
        if (_activeTab is null || _loadingTab)
        {
            return;
        }
        _activeTab.Curl = CurlBox.Text;
        _activeTab.Method = SelectedMethod();
        _activeTab.Url = UrlBox.Text.Trim();
        _activeTab.Body = BodyBox.Text;
        _activeTab.PreRequestScript = PreRequestBox.Text;
        _activeTab.Headers = HeaderRows.Select(row => new HeaderEntry
        {
            IsEnabled = row.IsEnabled,
            Name = row.Name,
            Value = row.Value,
        }).ToList();
        _activeTab.VerifySsl = VerifySslToggle.IsOn;
        _activeTab.FollowRedirects = RedirectToggle.IsOn;
        _activeTab.AutoDecode = AutoDecodeToggle.IsOn;
        _activeTab.TimeoutSeconds = (int)Math.Clamp(TimeoutBox.Value, 1, 3600);
        _activeTab.Repeat = (int)Math.Clamp(RepeatBox.Value, 1, 1000);
    }

    private void ParseCurl_Click(object sender, RoutedEventArgs e) => ParseCurlIntoEditor();

    private bool ParseCurlIntoEditor()
    {
        try
        {
            var parsed = CurlParser.Parse(CurlBox.Text);
            SelectMethod(parsed.Method);
            UrlBox.Text = parsed.Url;
            BodyBox.Text = parsed.Body;
            TimeoutBox.Value = parsed.TimeoutSeconds;
            VerifySslToggle.IsOn = parsed.VerifySsl;
            RedirectToggle.IsOn = parsed.FollowRedirects;
            SetHeaderRows(parsed.Headers.Select(pair => new HeaderEntry { Name = pair.Key, Value = pair.Value }));
            RequestInfoBar.IsOpen = false;
            SaveActiveTab();
            UpdateEnvironmentHint();
            return true;
        }
        catch (Exception ex)
        {
            ShowError(ex.Message);
            return false;
        }
    }

    private void BuildCurl_Click(object sender, RoutedEventArgs e)
    {
        var request = BuildRequest(applyEnvironment: false, AppServices.State.ActiveVariables);
        CurlBox.Text = CurlParser.Serialize(request);
        SaveActiveTab();
    }

    private void SetHeaderRows(IEnumerable<HeaderEntry> rows)
    {
        foreach (var row in HeaderRows)
        {
            row.PropertyChanged -= HeaderRow_PropertyChanged;
        }
        HeaderRows.Clear();
        foreach (var row in rows)
        {
            row.PropertyChanged += HeaderRow_PropertyChanged;
            HeaderRows.Add(row);
        }
    }

    private void AddHeader_Click(object sender, RoutedEventArgs e)
    {
        var row = new HeaderEntry();
        row.PropertyChanged += HeaderRow_PropertyChanged;
        HeaderRows.Add(row);
    }

    private void DeleteHeader_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is HeaderEntry row)
        {
            row.PropertyChanged -= HeaderRow_PropertyChanged;
            HeaderRows.Remove(row);
            UpdateEnvironmentHint();
        }
    }

    private void ClearHeaders_Click(object sender, RoutedEventArgs e) => SetHeaderRows([]);
    private void HeaderRow_PropertyChanged(object? sender, PropertyChangedEventArgs e) => UpdateEnvironmentHint();

    private void RequestField_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (!_loadingTab)
        {
            UpdateEnvironmentHint();
        }
    }

    private void UpdateEnvironmentHint()
    {
        if (EnvironmentHintText is null)
        {
            return;
        }
        var allText = string.Join("\n", new[] { CurlBox.Text, UrlBox.Text, BodyBox.Text }
            .Concat(HeaderRows.Select(row => $"{row.Name}:{row.Value}")));
        var missing = EnvironmentService.Missing(allText, AppServices.State.ActiveVariables);
        EnvironmentHintText.Text = missing.Count == 0
            ? $"Environment: {AppServices.State.ActiveEnvironment}"
            : $"Missing in {AppServices.State.ActiveEnvironment}: {string.Join(", ", missing)}";
    }

    private async void ImportCurl_Click(object sender, RoutedEventArgs e)
    {
        var picker = new FileOpenPicker();
        picker.FileTypeFilter.Add(".txt");
        picker.FileTypeFilter.Add(".curl");
        picker.FileTypeFilter.Add(".json");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
        var file = await picker.PickSingleFileAsync();
        if (file is null)
        {
            return;
        }
        CurlBox.Text = await FileIO.ReadTextAsync(file);
        ParseCurlIntoEditor();
    }

    private void BeautifyBody_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var source = BodyBox.Text;
            try
            {
                source = JsonSerializer.Deserialize<string>(source) ?? source;
            }
            catch
            {
                // The input may already be regular JSON.
            }
            using var document = JsonDocument.Parse(source);
            BodyBox.Text = JsonSerializer.Serialize(document.RootElement, new JsonSerializerOptions { WriteIndented = true });
            RequestEditorTabs.SelectedIndex = 2;
        }
        catch (Exception ex)
        {
            ShowError($"Body is not valid JSON: {ex.Message}");
        }
    }

    private void ClearRequest_Click(object sender, RoutedEventArgs e)
    {
        CurlBox.Text = "";
        UrlBox.Text = "";
        BodyBox.Text = "";
        PreRequestBox.Text = "";
        SelectMethod("GET");
        SetHeaderRows([]);
        DisplayResponse(new RequestTabSession());
        SaveActiveTab();
    }

    private async void SaveCollection_Click(object sender, RoutedEventArgs e)
    {
        SaveActiveTab();
        if (_activeTab is null)
        {
            return;
        }
        if (AppServices.State.Collections.Count == 0)
        {
            AppServices.State.Collections["Default"] = [];
        }
        var collection = new ComboBox
        {
            Header = "Collection",
            ItemsSource = AppServices.State.Collections.Keys.OrderBy(name => name).ToList(),
            SelectedIndex = 0,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        var name = new TextBox { Header = "Request name", Text = _activeTab.Name };
        var panel = new StackPanel { Spacing = 10 };
        panel.Children.Add(collection);
        panel.Children.Add(name);
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = "Save to collection",
            Content = panel,
            PrimaryButtonText = "Save",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync() != ContentDialogResult.Primary ||
            collection.SelectedItem is not string collectionName)
        {
            return;
        }
        var request = BuildRequest(applyEnvironment: false, AppServices.State.ActiveVariables);
        AppServices.State.Collections[collectionName].Add(new SavedRequest
        {
            Name = string.IsNullOrWhiteSpace(name.Text) ? _activeTab.Name : name.Text.Trim(),
            Method = request.Method,
            Curl = CurlParser.Serialize(request),
        });
        await AppServices.State.SaveCollectionsAsync();
        ShowMessage("Request saved to collection.", InfoBarSeverity.Success);
    }

    private async void SendButton_Click(object sender, RoutedEventArgs e)
    {
        SaveActiveTab();
        if (_activeTab is null)
        {
            return;
        }
        if (string.IsNullOrWhiteSpace(_activeTab.Url) && !string.IsNullOrWhiteSpace(_activeTab.Curl) && !ParseCurlIntoEditor())
        {
            return;
        }
        SetBusy(true);
        try
        {
            var script = PreRequestScriptService.Run(PreRequestBox.Text, AppServices.State.ActiveVariables);
            _activeTab.ScriptLog = string.Join(Environment.NewLine, script.Logs);
            var request = BuildRequest(applyEnvironment: true, script.Environment);
            _requestCancellation = new CancellationTokenSource();
            var response = await _apiClient.SendAsync(request, _requestCancellation.Token);
            _activeTab.Response = response;
            _activeTab.ResponseInfo =
                $"Method: {request.Method}{Environment.NewLine}" +
                $"URL: {request.Url}{Environment.NewLine}" +
                $"Attempts: {response.Attempts}{Environment.NewLine}" +
                $"Encoding: {response.EncodingName}{Environment.NewLine}" +
                $"Verify SSL: {request.VerifySsl}{Environment.NewLine}" +
                $"Follow redirects: {request.FollowRedirects}";
            DisplayResponse(_activeTab);
            RequestInfoBar.IsOpen = false;
            var storageRequest = BuildRequest(applyEnvironment: false, AppServices.State.ActiveVariables);
            await AppServices.State.AddHistoryAsync(new HistoryEntry
            {
                Method = request.Method,
                Url = request.Url,
                Curl = CurlParser.Serialize(storageRequest),
                Status = response.StatusCode,
                Elapsed = response.ElapsedMilliseconds,
                Repeat = request.Repeat,
            });
            PublishWorkspace();
            RunResponseSearch(1, reset: true);
        }
        catch (OperationCanceledException)
        {
            ShowError("Request cancelled.");
        }
        catch (Exception ex)
        {
            ShowError(ex.Message);
        }
        finally
        {
            _requestCancellation?.Dispose();
            _requestCancellation = null;
            SetBusy(false);
        }
    }

    private ApiRequestDefinition BuildRequest(bool applyEnvironment, IReadOnlyDictionary<string, string> environment)
    {
        string Resolve(string text) => applyEnvironment ? EnvironmentService.Apply(text, environment) : text;
        var request = new ApiRequestDefinition
        {
            Method = SelectedMethod(),
            Url = Resolve(UrlBox.Text.Trim()),
            Body = Resolve(BodyBox.Text),
            TimeoutSeconds = (int)Math.Clamp(TimeoutBox.Value, 1, 3600),
            Repeat = (int)Math.Clamp(RepeatBox.Value, 1, 1000),
            VerifySsl = VerifySslToggle.IsOn,
            FollowRedirects = RedirectToggle.IsOn,
            AutoDecode = AutoDecodeToggle.IsOn,
        };
        foreach (var row in HeaderRows.Where(row => row.IsEnabled && !string.IsNullOrWhiteSpace(row.Name)))
        {
            request.Headers.Add(new(Resolve(row.Name.Trim()), Resolve(row.Value)));
        }
        return request;
    }

    private void DisplayResponse(RequestTabSession tab)
    {
        var response = tab.Response;
        StatusText.Text = response is null ? "No response" : $"{response.StatusCode} {response.Reason}";
        TimeText.Text = response is null ? "" : $"{response.ElapsedMilliseconds} ms";
        SizeText.Text = response is null ? "" : FormatSize(response.SizeBytes);
        ResponseBodyBox.Text = response is null ? "" : FormatResponseBody(response.Body);
        ResponseHeadersBox.Text = response?.Headers ?? "";
        ResponseInfoBox.Text = tab.ResponseInfo;
        ResponseLogBox.Text = tab.ScriptLog;
        ResponseAiBox.Text = tab.AiAnalysis;
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e) => _requestCancellation?.Cancel();

    private void SetBusy(bool busy)
    {
        SendButton.IsEnabled = !busy;
        CancelButton.IsEnabled = busy;
        RequestProgress.IsActive = busy;
    }

    private void ShowError(string message) => ShowMessage(message, InfoBarSeverity.Error);

    private void ShowMessage(string message, InfoBarSeverity severity)
    {
        RequestInfoBar.Message = message;
        RequestInfoBar.Severity = severity;
        RequestInfoBar.IsOpen = true;
    }

    private async void CopyResponse_Click(object sender, RoutedEventArgs e)
    {
        var package = new DataPackage();
        package.SetText(ResponseBodyBox.Text);
        Clipboard.SetContent(package);
        await Task.CompletedTask;
    }

    private async void SaveResponse_Click(object sender, RoutedEventArgs e)
    {
        if (_activeTab?.Response is not ApiResponseResult response)
        {
            ShowError("Send a request before saving a response.");
            return;
        }
        var picker = new FileSavePicker { SuggestedFileName = "response" };
        picker.FileTypeChoices.Add("JSON", [".json"]);
        picker.FileTypeChoices.Add("Text", [".txt"]);
        picker.FileTypeChoices.Add("Binary", [".bin"]);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, App.MainWindowInstance!.WindowHandle);
        var file = await picker.PickSaveFileAsync();
        if (file is not null)
        {
            await FileIO.WriteBytesAsync(file, response.RawBytes);
        }
    }

    private void AnalyzeResponse_Click(object sender, RoutedEventArgs e)
    {
        SaveActiveTab();
        PublishWorkspace();
        App.MainWindowInstance?.NavigateTo("ai");
    }

    private void PublishWorkspace()
    {
        SaveActiveTab();
        AppServices.Workspace.PublishTabs(_tabs.ToList(), _activeTab);
    }

    private string SelectedMethod() => (MethodCombo.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "GET";

    private void SelectMethod(string method)
    {
        foreach (var item in MethodCombo.Items.OfType<ComboBoxItem>())
        {
            if (string.Equals(item.Content?.ToString(), method, StringComparison.OrdinalIgnoreCase))
            {
                MethodCombo.SelectedItem = item;
                return;
            }
        }
    }

    private static string FormatSize(long bytes) => bytes < 1024
        ? $"{bytes} B"
        : bytes < 1024 * 1024 ? $"{bytes / 1024d:F1} KB" : $"{bytes / (1024d * 1024d):F1} MB";

    private static string FormatResponseBody(string body)
    {
        if (body.Length > 2_000_000)
        {
            return body;
        }
        try
        {
            using var document = JsonDocument.Parse(body);
            return JsonSerializer.Serialize(document.RootElement, new JsonSerializerOptions { WriteIndented = true });
        }
        catch
        {
            return body;
        }
    }

    private void ResponseSearchBox_TextChanged(object sender, TextChangedEventArgs e) => RunResponseSearch(1, reset: true);
    private void PreviousMatch_Click(object sender, RoutedEventArgs e) => RunResponseSearch(-1, reset: false);
    private void NextMatch_Click(object sender, RoutedEventArgs e) => RunResponseSearch(1, reset: false);
    private void ResponseTabs_SelectionChanged(object sender, SelectionChangedEventArgs e) => RunResponseSearch(1, reset: true);
    private void CaseSensitiveToggle_Click(object sender, RoutedEventArgs e) => RunResponseSearch(1, reset: true);

    private void SearchAccelerator_Invoked(KeyboardAccelerator sender, KeyboardAcceleratorInvokedEventArgs args)
    {
        ResponseSearchBox.Focus(FocusState.Programmatic);
        args.Handled = true;
    }

    private void RunResponseSearch(int direction, bool reset)
    {
        if (ResponseSearchBox is null || ResponseTabs is null)
        {
            return;
        }
        var query = ResponseSearchBox.Text;
        var target = ActiveResponseBox();
        if (string.IsNullOrEmpty(query) || string.IsNullOrEmpty(target.Text))
        {
            _searchIndex = -1;
            SearchCountText.Text = "";
            target.Select(0, 0);
            return;
        }
        var comparison = CaseSensitiveToggle.IsChecked == true ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        var matches = new List<int>();
        var offset = 0;
        while (offset <= target.Text.Length - query.Length && matches.Count < 10000)
        {
            var hit = target.Text.IndexOf(query, offset, comparison);
            if (hit < 0)
            {
                break;
            }
            matches.Add(hit);
            offset = hit + Math.Max(1, query.Length);
        }
        if (matches.Count == 0)
        {
            _searchIndex = -1;
            SearchCountText.Text = "0/0";
            return;
        }
        _searchIndex = reset || _searchIndex < 0 ? 0 : (_searchIndex + direction + matches.Count) % matches.Count;
        target.Focus(FocusState.Programmatic);
        target.Select(matches[_searchIndex], query.Length);
        SearchCountText.Text = $"{_searchIndex + 1}/{matches.Count}";
    }

    private TextBox ActiveResponseBox() => ResponseTabs.SelectedIndex switch
    {
        1 => ResponseHeadersBox,
        2 => ResponseInfoBox,
        3 => ResponseLogBox,
        4 => ResponseAiBox,
        _ => ResponseBodyBox,
    };
}
