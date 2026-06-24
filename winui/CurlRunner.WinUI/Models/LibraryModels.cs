using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json.Serialization;

namespace CurlRunner.WinUI.Models;

public sealed class HistoryEntry
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString("N")[..8];

    [JsonPropertyName("ts")]
    public string Timestamp { get; set; } = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");

    [JsonPropertyName("method")]
    public string Method { get; set; } = "GET";

    [JsonPropertyName("url")]
    public string Url { get; set; } = "";

    [JsonPropertyName("curl")]
    public string Curl { get; set; } = "";

    [JsonPropertyName("status")]
    public int Status { get; set; }

    [JsonPropertyName("elapsed")]
    public long Elapsed { get; set; }

    [JsonPropertyName("repeat")]
    public int Repeat { get; set; } = 1;
}

public sealed class SavedRequest
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = Guid.NewGuid().ToString("N")[..8];

    [JsonPropertyName("name")]
    public string Name { get; set; } = "Request";

    [JsonPropertyName("method")]
    public string Method { get; set; } = "GET";

    [JsonPropertyName("curl")]
    public string Curl { get; set; } = "";
}

public sealed class HeaderEntry : INotifyPropertyChanged
{
    private bool _isEnabled = true;
    private string _name = "";
    private string _value = "";

    public bool IsEnabled
    {
        get => _isEnabled;
        set => SetField(ref _isEnabled, value);
    }

    public string Name
    {
        get => _name;
        set => SetField(ref _name, value);
    }

    public string Value
    {
        get => _value;
        set => SetField(ref _value, value);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void SetField<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return;
        }
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class RequestTabSession
{
    public string Id { get; init; } = Guid.NewGuid().ToString("N")[..8];
    public string Name { get; set; } = "Request";
    public string Method { get; set; } = "GET";
    public string Url { get; set; } = "";
    public string Curl { get; set; } = "";
    public List<HeaderEntry> Headers { get; set; } = [];
    public string Body { get; set; } = "";
    public string PreRequestScript { get; set; } = "";
    public bool VerifySsl { get; set; } = true;
    public bool FollowRedirects { get; set; } = true;
    public bool AutoDecode { get; set; } = true;
    public int TimeoutSeconds { get; set; } = 30;
    public int Repeat { get; set; } = 1;
    public ApiResponseResult? Response { get; set; }
    public string ResponseInfo { get; set; } = "";
    public string ScriptLog { get; set; } = "";
    public string AiAnalysis { get; set; } = "";
}

public sealed class AppSettings
{
    public string Theme { get; set; } = "system";
    public bool MicaEnabled { get; set; } = true;
    public int DefaultTimeoutSeconds { get; set; } = 30;
    public bool DefaultVerifySsl { get; set; } = true;
    public bool DefaultFollowRedirects { get; set; } = true;
    public bool DefaultAutoDecode { get; set; } = true;
    public string AiProvider { get; set; } = "ollama";
    public string OllamaBaseUrl { get; set; } = "http://localhost:11434";
    public string OllamaModel { get; set; } = "llama3.2";
    public string OpenAiModel { get; set; } = "gpt-5.4-mini";
}

public sealed class EnvironmentVariableRow : INotifyPropertyChanged
{
    private string _name = "";
    private string _value = "";

    public string Name
    {
        get => _name;
        set => SetField(ref _name, value);
    }

    public string Value
    {
        get => _value;
        set => SetField(ref _value, value);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void SetField(ref string field, string value, [CallerMemberName] string? name = null)
    {
        if (field == value)
        {
            return;
        }
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}

public sealed class ComparePanelModel : INotifyPropertyChanged
{
    private string _name = "Panel";
    private string _input = "";
    private string _output = "";

    public string Id { get; } = Guid.NewGuid().ToString("N")[..8];
    public List<string> DiffLines { get; set; } = [];

    public string Name
    {
        get => _name;
        set => SetField(ref _name, value);
    }

    public string Input
    {
        get => _input;
        set => SetField(ref _input, value);
    }

    public string Output
    {
        get => _output;
        set => SetField(ref _output, value);
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void SetField(ref string field, string value, [CallerMemberName] string? name = null)
    {
        if (field == value)
        {
            return;
        }
        field = value;
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
