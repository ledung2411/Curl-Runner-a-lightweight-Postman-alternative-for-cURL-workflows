using CurlRunner.WinUI.Models;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Collections.ObjectModel;

namespace CurlRunner.WinUI.Pages;

public sealed partial class EnvironmentsPage : Page
{
    public ObservableCollection<EnvironmentVariableRow> Variables { get; } = [];
    private string? _selectedName;

    public EnvironmentsPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
        Loaded += (_, _) => RefreshEnvironmentList();
    }

    private void RefreshEnvironmentList(string? select = null)
    {
        EnvironmentList.ItemsSource = AppServices.State.Environments.Keys
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToList();
        EnvironmentList.SelectedItem = select ?? _selectedName ?? AppServices.State.ActiveEnvironment;
        if (EnvironmentList.SelectedItem is null && EnvironmentList.Items.Count > 0)
        {
            EnvironmentList.SelectedIndex = 0;
        }
    }

    private void EnvironmentList_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        _selectedName = EnvironmentList.SelectedItem?.ToString();
        EnvironmentTitle.Text = _selectedName is null
            ? "Select an environment"
            : _selectedName == AppServices.State.ActiveEnvironment ? $"{_selectedName} (active)" : _selectedName;
        Variables.Clear();
        if (_selectedName is null || !AppServices.State.Environments.TryGetValue(_selectedName, out var values))
        {
            return;
        }
        foreach (var pair in values.OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase))
        {
            Variables.Add(new EnvironmentVariableRow { Name = pair.Key, Value = pair.Value });
        }
    }

    private void AddVariable_Click(object sender, RoutedEventArgs e) => Variables.Add(new EnvironmentVariableRow());

    private void DeleteVariable_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as Button)?.Tag is EnvironmentVariableRow row)
        {
            Variables.Remove(row);
        }
    }

    private async void SaveEnvironment_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedName is null)
        {
            return;
        }
        var duplicate = Variables
            .Where(row => !string.IsNullOrWhiteSpace(row.Name))
            .GroupBy(row => row.Name.Trim(), StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault(group => group.Count() > 1);
        if (duplicate is not null)
        {
            ShowMessage($"Duplicate variable: {duplicate.Key}", InfoBarSeverity.Error);
            return;
        }
        AppServices.State.Environments[_selectedName] = Variables
            .Where(row => !string.IsNullOrWhiteSpace(row.Name))
            .ToDictionary(row => row.Name.Trim(), row => row.Value, StringComparer.OrdinalIgnoreCase);
        await AppServices.State.SaveEnvironmentsAsync();
        ShowMessage("Environment saved.", InfoBarSeverity.Success);
    }

    private async void NewEnvironment_Click(object sender, RoutedEventArgs e)
    {
        var name = await PromptAsync("New environment", "Environment name");
        if (string.IsNullOrWhiteSpace(name) || AppServices.State.Environments.ContainsKey(name))
        {
            return;
        }
        AppServices.State.Environments[name] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        await AppServices.State.SaveEnvironmentsAsync();
        RefreshEnvironmentList(name);
    }

    private async void RenameEnvironment_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedName is null)
        {
            return;
        }
        var oldName = _selectedName;
        var name = await PromptAsync("Rename environment", "Environment name", oldName);
        if (string.IsNullOrWhiteSpace(name) ||
            (!string.Equals(name, oldName, StringComparison.OrdinalIgnoreCase) && AppServices.State.Environments.ContainsKey(name)))
        {
            return;
        }
        var values = AppServices.State.Environments[oldName];
        AppServices.State.Environments.Remove(oldName);
        AppServices.State.Environments[name] = values;
        if (AppServices.State.ActiveEnvironment == oldName)
        {
            AppServices.State.SetActiveEnvironment(name);
        }
        await AppServices.State.SaveEnvironmentsAsync();
        RefreshEnvironmentList(name);
    }

    private async void DeleteEnvironment_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedName is null || AppServices.State.Environments.Count <= 1)
        {
            ShowMessage("At least one environment is required.", InfoBarSeverity.Warning);
            return;
        }
        var deleting = _selectedName;
        AppServices.State.Environments.Remove(deleting);
        if (AppServices.State.ActiveEnvironment == deleting)
        {
            AppServices.State.SetActiveEnvironment(AppServices.State.Environments.Keys.First());
        }
        await AppServices.State.SaveEnvironmentsAsync();
        _selectedName = null;
        RefreshEnvironmentList();
    }

    private void SetActive_Click(object sender, RoutedEventArgs e)
    {
        if (_selectedName is null)
        {
            return;
        }
        AppServices.State.SetActiveEnvironment(_selectedName);
        EnvironmentTitle.Text = $"{_selectedName} (active)";
        ShowMessage("Active environment updated.", InfoBarSeverity.Success);
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

    private void ShowMessage(string message, InfoBarSeverity severity)
    {
        EnvironmentInfoBar.Message = message;
        EnvironmentInfoBar.Severity = severity;
        EnvironmentInfoBar.IsOpen = true;
    }
}
