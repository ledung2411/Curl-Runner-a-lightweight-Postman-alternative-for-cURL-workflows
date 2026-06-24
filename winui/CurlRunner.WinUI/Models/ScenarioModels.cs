using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json.Serialization;

namespace CurlRunner.WinUI.Models;

public sealed class ScenarioDefinition
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "Untitled Scenario";

    [JsonPropertyName("steps")]
    public List<ScenarioStepDefinition> Steps { get; set; } = [];
}

public sealed class ScenarioStepDefinition
{
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "Step";

    [JsonPropertyName("curl")]
    public string Curl { get; set; } = "";

    [JsonPropertyName("group")]
    public int Group { get; set; } = 1;

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; } = true;

    [JsonPropertyName("extractors")]
    public string Extractors { get; set; } = "";

    [JsonPropertyName("assertions")]
    public string Assertions { get; set; } = "";
}

public sealed class ScenarioStepRow : INotifyPropertyChanged
{
    private string _status = "Not run";
    private string _elapsed = "";

    public ScenarioStepDefinition Definition { get; set; } = new();
    public int Order { get; set; }
    public string Name => Definition.Name;
    public int Group => Definition.Group;
    public string Method { get; set; } = "";
    public string Url { get; set; } = "";
    public ScenarioStepResult? Result { get; set; }

    public string Status
    {
        get => _status;
        set => SetField(ref _status, value);
    }

    public string Elapsed
    {
        get => _elapsed;
        set => SetField(ref _elapsed, value);
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

public sealed class ScenarioStepResult
{
    public bool Passed { get; init; }
    public bool Skipped { get; init; }
    public int StatusCode { get; init; }
    public string Reason { get; init; } = "";
    public long ElapsedMilliseconds { get; init; }
    public string Method { get; init; } = "";
    public string Url { get; init; } = "";
    public string Error { get; init; } = "";
    public List<string> AssertionDetails { get; init; } = [];
    public List<string> ExtractDetails { get; init; } = [];
    public Dictionary<string, string> ExtractedValues { get; init; } = new(StringComparer.OrdinalIgnoreCase);
}
