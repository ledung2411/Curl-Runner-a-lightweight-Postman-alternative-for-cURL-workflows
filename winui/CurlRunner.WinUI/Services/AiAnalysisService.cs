using CurlRunner.WinUI.Models;
using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CurlRunner.WinUI.Services;

public sealed partial class AiAnalysisService
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);

    [GeneratedRegex(@"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")]
    private static partial Regex BearerPattern();

    [GeneratedRegex(@"(?i)([?&](?:token|key|api_key|apikey|secret|password|auth|signature)=)[^&]*")]
    private static partial Regex SensitiveQueryPattern();

    [GeneratedRegex("""(?i)("?(?:access_token|refresh_token|token|api_key|apikey|secret|password|passwd)"?\s*[:=]\s*"?)[^",\s}\]]+("?)""")]
    private static partial Regex SensitiveBodyPattern();

    [GeneratedRegex(@"(?i)authorization|cookie|set-cookie|token|api[-_]?key|secret|password|signature")]
    private static partial Regex SensitiveNamePattern();

    public async Task<OllamaStatus> GetOllamaStatusAsync(
        string baseUrl,
        string preferredModel,
        CancellationToken cancellationToken = default)
    {
        var executable = FindOllamaExecutable();
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(4) };
            using var response = await client.GetAsync($"{baseUrl.TrimEnd('/')}/api/tags", cancellationToken);
            response.EnsureSuccessStatusCode();
            await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
            using var document = await JsonDocument.ParseAsync(stream, cancellationToken: cancellationToken);
            var models = document.RootElement.TryGetProperty("models", out var values)
                ? values.EnumerateArray()
                    .Select(item => item.TryGetProperty("name", out var name) ? name.GetString() ?? "" : "")
                    .Where(name => name.Length > 0)
                    .ToList()
                : [];
            var selected = models.FirstOrDefault(name =>
                string.Equals(name, preferredModel, StringComparison.OrdinalIgnoreCase) ||
                name.StartsWith(preferredModel + ":", StringComparison.OrdinalIgnoreCase));
            return new OllamaStatus(executable is not null, true, models, selected, null);
        }
        catch (Exception ex)
        {
            return new OllamaStatus(executable is not null, false, [], null, ex.Message);
        }
    }

    public async Task<(string Analysis, string Model)> AnalyzeWithOllamaAsync(
        string context,
        string baseUrl,
        string preferredModel,
        CancellationToken cancellationToken = default)
    {
        var status = await GetOllamaStatusAsync(baseUrl, preferredModel, cancellationToken);
        if (!status.ServerRunning)
        {
            throw new InvalidOperationException("Cannot connect to Ollama. Install or start Ollama first.");
        }
        var model = status.SelectedModel ?? status.Models.FirstOrDefault();
        if (model is null)
        {
            throw new InvalidOperationException($"No Ollama model installed. Pull {preferredModel} first.");
        }
        using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(4) };
        var payload = new
        {
            model,
            prompt = VietnameseInstructions + "\n\n" + context,
            stream = false,
            options = new { temperature = 0.2, num_predict = 1000 },
        };
        using var response = await client.PostAsync(
            $"{baseUrl.TrimEnd('/')}/api/generate",
            JsonContent(payload),
            cancellationToken);
        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"Ollama API error ({(int)response.StatusCode}): {ExtractError(raw)}");
        }
        using var document = JsonDocument.Parse(raw);
        var analysis = document.RootElement.TryGetProperty("response", out var value) ? value.GetString() : null;
        if (string.IsNullOrWhiteSpace(analysis))
        {
            throw new InvalidOperationException("Ollama returned no analysis text.");
        }
        return (analysis.Trim(), model);
    }

    public async Task<string> AnalyzeWithOpenAiAsync(
        string context,
        string apiKey,
        string model,
        CancellationToken cancellationToken = default)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(100) };
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
        var payload = new
        {
            model,
            store = false,
            max_output_tokens = 1200,
            instructions = VietnameseInstructions,
            input = "Analyze this redacted HTTP request/response context. Do not reconstruct secrets.\n\n" + context,
        };
        using var response = await client.PostAsync(
            "https://api.openai.com/v1/responses",
            JsonContent(payload),
            cancellationToken);
        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"OpenAI API error ({(int)response.StatusCode}): {ExtractError(raw)}");
        }
        using var document = JsonDocument.Parse(raw);
        if (document.RootElement.TryGetProperty("output_text", out var outputText) &&
            !string.IsNullOrWhiteSpace(outputText.GetString()))
        {
            return outputText.GetString()!.Trim();
        }
        var parts = new List<string>();
        if (document.RootElement.TryGetProperty("output", out var output))
        {
            foreach (var item in output.EnumerateArray())
            {
                if (!item.TryGetProperty("content", out var content))
                {
                    continue;
                }
                foreach (var block in content.EnumerateArray())
                {
                    if (block.TryGetProperty("text", out var text) && text.GetString() is string value)
                    {
                        parts.Add(value);
                    }
                }
            }
        }
        if (parts.Count == 0)
        {
            throw new InvalidOperationException("OpenAI returned no analysis text.");
        }
        return string.Join(Environment.NewLine, parts).Trim();
    }

    public string BuildContext(RequestTabSession tab)
    {
        if (tab.Response is null)
        {
            throw new InvalidOperationException("Send a request before running AI analysis.");
        }
        var requestHeaders = tab.Headers
            .Where(row => row.IsEnabled && !string.IsNullOrWhiteSpace(row.Name))
            .GroupBy(row => row.Name, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => SensitiveNamePattern().IsMatch(group.Key) ? "[REDACTED]" : Redact(group.Last().Value),
                StringComparer.OrdinalIgnoreCase);
        var responseHeaders = tab.Response.Headers.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Split(':', 2))
            .ToDictionary(
                parts => parts[0],
                parts => SensitiveNamePattern().IsMatch(parts[0]) ? "[REDACTED]" : Redact(parts.Length > 1 ? parts[1].Trim() : ""),
                StringComparer.OrdinalIgnoreCase);
        var responseBody = Redact(tab.Response.Body);
        var truncated = responseBody.Length > 40000;
        if (truncated)
        {
            responseBody = responseBody[..40000] + $"\n[AI context truncated from {tab.Response.Body.Length:N0} characters]";
        }
        var body = Redact(tab.Body);
        if (body.Length > 12000)
        {
            body = body[..12000] + "\n[Request body truncated for AI context]";
        }
        return JsonSerializer.Serialize(new
        {
            request = new { method = tab.Method, url = Redact(tab.Url), headers = requestHeaders, body_preview = body },
            response = new
            {
                status = $"{tab.Response.StatusCode} {tab.Response.Reason}",
                headers = responseHeaders,
                encoding = tab.Response.EncodingName,
                size_bytes = tab.Response.SizeBytes,
                body_preview = responseBody,
            },
        }, new JsonSerializerOptions { WriteIndented = true });
    }

    public async Task<int> InstallOllamaAsync(Action<string> log, CancellationToken cancellationToken)
    {
        return await RunProcessAsync(
            "winget",
            "install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements",
            log,
            cancellationToken);
    }

    public void StartOllama()
    {
        var executable = FindOllamaExecutable() ?? throw new InvalidOperationException("Ollama executable was not found.");
        Process.Start(new ProcessStartInfo(executable, "serve")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        });
    }

    public async Task<int> PullModelAsync(string model, Action<string> log, CancellationToken cancellationToken)
    {
        var executable = FindOllamaExecutable() ?? throw new InvalidOperationException("Ollama executable was not found.");
        return await RunProcessAsync(executable, $"pull {model}", log, cancellationToken);
    }

    public static string? FindOllamaExecutable()
    {
        var candidates = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Ollama", "ollama.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Ollama", "ollama.exe"),
        };
        var direct = candidates.FirstOrDefault(File.Exists);
        if (direct is not null)
        {
            return direct;
        }
        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            try
            {
                var path = Path.Combine(directory.Trim(), "ollama.exe");
                if (File.Exists(path))
                {
                    return path;
                }
            }
            catch
            {
                // Ignore invalid PATH entries.
            }
        }
        return null;
    }

    private static async Task<int> RunProcessAsync(
        string executable,
        string arguments,
        Action<string> log,
        CancellationToken cancellationToken)
    {
        using var process = new Process
        {
            StartInfo = new ProcessStartInfo(executable, arguments)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
            },
        };
        process.OutputDataReceived += (_, args) => { if (!string.IsNullOrWhiteSpace(args.Data)) log(args.Data); };
        process.ErrorDataReceived += (_, args) => { if (!string.IsNullOrWhiteSpace(args.Data)) log(args.Data); };
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await process.WaitForExitAsync(cancellationToken);
        return process.ExitCode;
    }

    private static StringContent JsonContent<T>(T value) =>
        new(JsonSerializer.Serialize(value, JsonOptions), Encoding.UTF8, "application/json");

    private static string Redact(string text) => SensitiveBodyPattern().Replace(
        SensitiveQueryPattern().Replace(BearerPattern().Replace(text ?? "", "$1[REDACTED]"), "$1[REDACTED]"),
        "$1[REDACTED]$2");

    private static string ExtractError(string raw)
    {
        try
        {
            using var document = JsonDocument.Parse(raw);
            if (document.RootElement.TryGetProperty("error", out var error))
            {
                if (error.ValueKind == JsonValueKind.Object && error.TryGetProperty("message", out var message))
                {
                    return message.GetString() ?? error.ToString();
                }
                return error.ToString();
            }
        }
        catch
        {
            // Return a bounded raw error below.
        }
        return string.IsNullOrWhiteSpace(raw) ? "Empty error response" : raw[..Math.Min(raw.Length, 800)];
    }

    private const string VietnameseInstructions =
        "Tra loi bang tieng Viet ro rang, thuc te cho lap trinh vien. Ban la tro ly debug API cap cao. " +
        "Hay phan tich request/response da duoc che thong tin nhay cam, tim loi backend/client, input, auth, schema, " +
        "timeout, rate limit va noi dung bat thuong. Neu response binh thuong, noi ro. Trinh bay ngan gon theo cac muc: " +
        "Tom tat, Bang chung, Nguyen nhan co kha nang, Cach sua, Kiem tra tiep theo. Khong khoi phuc secret.";
}

public sealed record OllamaStatus(
    bool CliInstalled,
    bool ServerRunning,
    IReadOnlyList<string> Models,
    string? SelectedModel,
    string? Error)
{
    public bool Ready => CliInstalled && ServerRunning && SelectedModel is not null;
}
