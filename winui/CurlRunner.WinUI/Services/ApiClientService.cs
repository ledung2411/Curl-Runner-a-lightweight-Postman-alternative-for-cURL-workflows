using CurlRunner.WinUI.Models;
using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;

namespace CurlRunner.WinUI.Services;

public sealed class ApiClientService
{
    static ApiClientService()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
    }

    public async Task<ApiResponseResult> SendAsync(
        ApiRequestDefinition definition,
        CancellationToken cancellationToken = default)
    {
        if (!Uri.TryCreate(definition.Url, UriKind.Absolute, out _))
        {
            throw new ArgumentException("Enter a valid absolute URL.");
        }

        using var handler = new HttpClientHandler
        {
            AllowAutoRedirect = definition.FollowRedirects,
        };
        if (!definition.VerifySsl)
        {
            handler.ServerCertificateCustomValidationCallback =
                HttpClientHandler.DangerousAcceptAnyServerCertificateValidator;
        }

        using var client = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(Math.Clamp(definition.TimeoutSeconds, 1, 3600)),
        };

        ApiResponseResult? finalResult = null;
        var attempts = Math.Clamp(definition.Repeat, 1, 1000);
        for (var attempt = 1; attempt <= attempts; attempt++)
        {
            using var request = BuildRequest(definition);
            var stopwatch = Stopwatch.StartNew();
            using var response = await client.SendAsync(
                request,
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            var bytes = await response.Content.ReadAsByteArrayAsync(cancellationToken);
            stopwatch.Stop();

            var encoding = ResolveEncoding(bytes, response.Content.Headers.ContentType?.CharSet, definition.AutoDecode);

            var headerLines = response.Headers
                .Concat(response.Content.Headers)
                .Select(header => $"{header.Key}: {string.Join(", ", header.Value)}");
            finalResult = new ApiResponseResult
            {
                StatusCode = (int)response.StatusCode,
                Reason = response.ReasonPhrase ?? "",
                Body = encoding.GetString(bytes),
                Headers = string.Join(Environment.NewLine, headerLines),
                ElapsedMilliseconds = stopwatch.ElapsedMilliseconds,
                SizeBytes = bytes.LongLength,
                Attempts = attempt,
                RawBytes = bytes,
                EncodingName = encoding.WebName,
            };
        }

        return finalResult!;
    }

    private static Encoding ResolveEncoding(byte[] bytes, string? charset, bool autoDecode)
    {
        if (!autoDecode)
        {
            return Encoding.UTF8;
        }
        try
        {
            if (!string.IsNullOrWhiteSpace(charset))
            {
                return Encoding.GetEncoding(charset.Trim('"'));
            }
        }
        catch
        {
            // Continue with byte-level detection.
        }
        if (bytes.AsSpan().StartsWith(new byte[] { 0xEF, 0xBB, 0xBF }))
        {
            return Encoding.UTF8;
        }
        if (bytes.AsSpan().StartsWith(new byte[] { 0xFF, 0xFE }))
        {
            return Encoding.Unicode;
        }
        try
        {
            _ = new UTF8Encoding(false, true).GetString(bytes);
            return Encoding.UTF8;
        }
        catch (DecoderFallbackException)
        {
            return Encoding.GetEncoding(1252);
        }
    }

    private static HttpRequestMessage BuildRequest(ApiRequestDefinition definition)
    {
        var request = new HttpRequestMessage(new HttpMethod(definition.Method), definition.Url);
        var contentType = definition.Headers.FirstOrDefault(
            pair => pair.Key.Equals("Content-Type", StringComparison.OrdinalIgnoreCase)).Value;

        if (!string.IsNullOrEmpty(definition.Body))
        {
            request.Content = new StringContent(definition.Body, Encoding.UTF8);
            if (!string.IsNullOrWhiteSpace(contentType))
            {
                request.Content.Headers.ContentType = MediaTypeHeaderValue.Parse(contentType);
            }
        }

        foreach (var (name, value) in definition.Headers)
        {
            if (name.Equals("Content-Type", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            if (!request.Headers.TryAddWithoutValidation(name, value))
            {
                request.Content ??= new ByteArrayContent([]);
                request.Content.Headers.TryAddWithoutValidation(name, value);
            }
        }
        return request;
    }
}
