using CurlRunner.WinUI.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Collections.ObjectModel;

namespace CurlRunner.WinUI.Pages;

public sealed partial class LibraryPage : Page
{
    public ObservableCollection<HistoryEntry> FilteredHistory { get; } = [];
    public ObservableCollection<SavedRequest> CollectionRequests { get; } = [];

    public LibraryPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
        Loaded += LibraryPage_Loaded;
        AppServices.State.HistoryChanged += (_, _) => DispatcherQueue.TryEnqueue(RefreshHistory);
        AppServices.State.CollectionsChanged += (_, _) => DispatcherQueue.TryEnqueue(RefreshCollections);
    }

    private void LibraryPage_Loaded(object sender, RoutedEventArgs e)
    {
        RefreshHistory();
        RefreshCollections();
    }

    private void HistorySearchBox_TextChanged(object sender, TextChangedEventArgs e) => RefreshHistory();

    private void RefreshHistory()
    {
        var query = HistorySearchBox?.Text.Trim() ?? "";
        FilteredHistory.Clear();
        foreach (var item in AppServices.State.History.Where(item =>
                     string.IsNullOrEmpty(query) ||
                     item.Method.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                     item.Url.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                     item.Status.ToString().Contains(query, StringComparison.OrdinalIgnoreCase)))
        {
            FilteredHistory.Add(item);
        }
    }

    private void RefreshCollections()
    {
        if (CollectionList is null)
        {
            return;
        }
        var selected = CollectionList.SelectedItem?.ToString();
        CollectionList.ItemsSource = AppServices.State.Collections.Keys
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
        if (selected is not null && AppServices.State.Collections.ContainsKey(selected))
        {
            CollectionList.SelectedItem = selected;
        }
        else if (CollectionList.Items.Count > 0)
        {
            CollectionList.SelectedIndex = 0;
        }
        RefreshCollectionRequests();
    }

    private void CollectionList_SelectionChanged(object sender, SelectionChangedEventArgs e) => RefreshCollectionRequests();

    private void RefreshCollectionRequests()
    {
        CollectionRequests.Clear();
        if (CollectionList.SelectedItem is not string name ||
            !AppServices.State.Collections.TryGetValue(name, out var requests))
        {
            return;
        }
        foreach (var request in requests)
        {
            CollectionRequests.Add(request);
        }
    }

    private void OpenHistory_Click(object sender, RoutedEventArgs e) => OpenHistory(newTab: false);
    private void OpenHistoryNewTab_Click(object sender, RoutedEventArgs e) => OpenHistory(newTab: true);
    private void HistoryList_DoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e) => OpenHistory(newTab: false);

    private void OpenHistory(bool newTab)
    {
        if (HistoryList.SelectedItem is not HistoryEntry item)
        {
            return;
        }
        AppServices.Workspace.RequestOpen(item.Method, item.Curl, newTab);
        App.MainWindowInstance?.NavigateTo("requests");
    }

    private async void DeleteHistory_Click(object sender, RoutedEventArgs e)
    {
        if (HistoryList.SelectedItem is HistoryEntry item)
        {
            AppServices.State.History.Remove(item);
            await AppServices.State.SaveHistoryAsync();
        }
    }

    private async void ClearHistory_Click(object sender, RoutedEventArgs e)
    {
        if (!await ConfirmAsync("Clear history?", "This removes every saved history entry."))
        {
            return;
        }
        AppServices.State.History.Clear();
        await AppServices.State.SaveHistoryAsync();
    }

    private async void NewCollection_Click(object sender, RoutedEventArgs e)
    {
        var name = await PromptAsync("New collection", "Collection name");
        if (string.IsNullOrWhiteSpace(name) || AppServices.State.Collections.ContainsKey(name))
        {
            return;
        }
        AppServices.State.Collections[name] = [];
        await AppServices.State.SaveCollectionsAsync();
        CollectionList.SelectedItem = name;
    }

    private async void RenameCollection_Click(object sender, RoutedEventArgs e)
    {
        if (CollectionList.SelectedItem is not string oldName)
        {
            return;
        }
        var name = await PromptAsync("Rename collection", "Collection name", oldName);
        if (string.IsNullOrWhiteSpace(name) ||
            (!string.Equals(name, oldName, StringComparison.OrdinalIgnoreCase) && AppServices.State.Collections.ContainsKey(name)))
        {
            return;
        }
        var items = AppServices.State.Collections[oldName];
        AppServices.State.Collections.Remove(oldName);
        AppServices.State.Collections[name] = items;
        await AppServices.State.SaveCollectionsAsync();
        CollectionList.SelectedItem = name;
    }

    private async void DeleteCollection_Click(object sender, RoutedEventArgs e)
    {
        if (CollectionList.SelectedItem is not string name ||
            !await ConfirmAsync("Delete collection?", $"Delete {name} and its saved requests?"))
        {
            return;
        }
        AppServices.State.Collections.Remove(name);
        await AppServices.State.SaveCollectionsAsync();
    }

    private void OpenCollectionRequest_Click(object sender, RoutedEventArgs e) => OpenCollectionRequest(newTab: false);
    private void OpenCollectionRequestNewTab_Click(object sender, RoutedEventArgs e) => OpenCollectionRequest(newTab: true);
    private void CollectionRequestList_DoubleTapped(object sender, Microsoft.UI.Xaml.Input.DoubleTappedRoutedEventArgs e) => OpenCollectionRequest(newTab: false);

    private void OpenCollectionRequest(bool newTab)
    {
        if (CollectionRequestList.SelectedItem is not SavedRequest item)
        {
            return;
        }
        AppServices.Workspace.RequestOpen(item.Name, item.Curl, newTab);
        App.MainWindowInstance?.NavigateTo("requests");
    }

    private async void RenameCollectionRequest_Click(object sender, RoutedEventArgs e)
    {
        if (CollectionRequestList.SelectedItem is not SavedRequest item)
        {
            return;
        }
        var name = await PromptAsync("Rename request", "Request name", item.Name);
        if (string.IsNullOrWhiteSpace(name))
        {
            return;
        }
        item.Name = name;
        await AppServices.State.SaveCollectionsAsync();
    }

    private async void DeleteCollectionRequest_Click(object sender, RoutedEventArgs e)
    {
        if (CollectionList.SelectedItem is not string collection ||
            CollectionRequestList.SelectedItem is not SavedRequest item)
        {
            return;
        }
        AppServices.State.Collections[collection].Remove(item);
        await AppServices.State.SaveCollectionsAsync();
    }

    private async Task<string?> PromptAsync(string title, string placeholder, string value = "")
    {
        var input = new TextBox { PlaceholderText = placeholder, Text = value };
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = title,
            Content = input,
            PrimaryButtonText = "Save",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary ? input.Text.Trim() : null;
    }

    private async Task<bool> ConfirmAsync(string title, string message)
    {
        var dialog = new ContentDialog
        {
            XamlRoot = XamlRoot,
            Title = title,
            Content = message,
            PrimaryButtonText = "Delete",
            CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
}
