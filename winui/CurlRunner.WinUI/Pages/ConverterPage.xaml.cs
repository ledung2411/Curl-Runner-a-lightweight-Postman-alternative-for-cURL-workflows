using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using System.Text.Json;
using Windows.ApplicationModel.DataTransfer;

namespace CurlRunner.WinUI.Pages;

public sealed partial class ConverterPage : Page
{
    private static readonly JsonSerializerOptions PrettyOptions = new() { WriteIndented = true };

    public ConverterPage()
    {
        InitializeComponent();
        NavigationCacheMode = Microsoft.UI.Xaml.Navigation.NavigationCacheMode.Required;
    }

    private void Convert_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            var mode = (ModeCombo.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "pretty";
            OutputBox.Text = mode switch
            {
                "pretty" => FormatJson(InputBox.Text, indented: true),
                "minify" => FormatJson(InputBox.Text, indented: false),
                "escape" => JsonSerializer.Serialize(InputBox.Text),
                "unescape" => UnescapeJsonString(InputBox.Text),
                "lines" => JsonSerializer.Serialize(
                    InputBox.Text.Replace("\r\n", "\n")
                        .Split('\n', StringSplitOptions.RemoveEmptyEntries),
                    PrettyOptions),
                _ => InputBox.Text,
            };
            ConverterInfoBar.IsOpen = false;
        }
        catch (Exception ex)
        {
            ConverterInfoBar.Message = ex.Message;
            ConverterInfoBar.IsOpen = true;
        }
    }

    private static string FormatJson(string input, bool indented)
    {
        using var document = JsonDocument.Parse(input);
        return JsonSerializer.Serialize(
            document.RootElement,
            indented ? PrettyOptions : new JsonSerializerOptions());
    }

    private static string UnescapeJsonString(string input)
    {
        var value = JsonSerializer.Deserialize<string>(input) ?? "";
        try
        {
            return FormatJson(value, indented: true);
        }
        catch
        {
            return value;
        }
    }

    private void Swap_Click(object sender, RoutedEventArgs e)
    {
        (InputBox.Text, OutputBox.Text) = (OutputBox.Text, InputBox.Text);
    }

    private void Copy_Click(object sender, RoutedEventArgs e)
    {
        var package = new DataPackage();
        package.SetText(OutputBox.Text);
        Clipboard.SetContent(package);
    }

    private void Clear_Click(object sender, RoutedEventArgs e)
    {
        InputBox.Text = "";
        OutputBox.Text = "";
        ConverterInfoBar.IsOpen = false;
    }

    private void LoadResponse_Click(object sender, RoutedEventArgs e)
    {
        var response = AppServices.Workspace.ActiveTab?.Response;
        if (response is null)
        {
            ConverterInfoBar.Message = "No response is available.";
            ConverterInfoBar.IsOpen = true;
            return;
        }
        InputBox.Text = response.Body;
        ConverterInfoBar.IsOpen = false;
    }

    private void WrapToggle_Toggled(object sender, RoutedEventArgs e)
    {
        if (InputBox is null || OutputBox is null)
        {
            return;
        }
        var wrapping = WrapToggle.IsOn ? TextWrapping.Wrap : TextWrapping.NoWrap;
        InputBox.TextWrapping = wrapping;
        OutputBox.TextWrapping = wrapping;
    }
}
