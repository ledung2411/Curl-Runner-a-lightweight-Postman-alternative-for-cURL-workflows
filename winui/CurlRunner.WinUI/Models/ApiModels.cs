namespace CurlRunner.WinUI.Models;

public sealed class ApiRequestDefinition
{
    public string Method { get; set; } = "GET";
    public string Url { get; set; } = "";
    public List<KeyValuePair<string, string>> Headers { get; } = [];
    public string Body { get; set; } = "";
    public int TimeoutSeconds { get; set; } = 30;
    public int Repeat { get; set; } = 1;
    public bool VerifySsl { get; set; } = true;
    public bool FollowRedirects { get; set; } = true;
    public bool AutoDecode { get; set; } = true;
}

public sealed class ApiResponseResult
{
    public int StatusCode { get; init; }
    public string Reason { get; init; } = "";
    public string Body { get; init; } = "";
    public string Headers { get; init; } = "";
    public long ElapsedMilliseconds { get; init; }
    public long SizeBytes { get; init; }
    public int Attempts { get; init; }
    public byte[] RawBytes { get; init; } = [];
    public string EncodingName { get; init; } = "UTF-8";
}
