using CurlRunner.WinUI.Models;
using CurlRunner.WinUI.Services;

namespace CurlRunner.WinUI.Tests;

public sealed class CoreServicesTests
{
    [Fact]
    public void CurlParser_RoundTripsBuilderFields()
    {
        var input = "curl -X POST 'https://api.test/items' -H 'Content-Type: application/json' --data-raw '{\"ok\":true}' --max-time 12";

        var parsed = CurlParser.Parse(input);
        var roundTrip = CurlParser.Parse(CurlParser.Serialize(parsed));

        Assert.Equal("POST", roundTrip.Method);
        Assert.Equal("https://api.test/items", roundTrip.Url);
        Assert.Contains(roundTrip.Headers, header => header.Key == "Content-Type" && header.Value == "application/json");
        Assert.Equal("{\"ok\":true}", roundTrip.Body);
        Assert.Equal(12, roundTrip.TimeoutSeconds);
    }

    [Fact]
    public void EnvironmentService_AppliesKnownAndReportsMissingVariables()
    {
        var variables = new Dictionary<string, string> { ["base_url"] = "https://api.test" };
        var source = "{{base_url}}/users/{{user_id}}";

        Assert.Equal("https://api.test/users/{{user_id}}", EnvironmentService.Apply(source, variables));
        Assert.Equal(["user_id"], EnvironmentService.Missing(source, variables));
    }

    [Fact]
    public void PreRequestScript_UpdatesRuntimeEnvironmentAndLogs()
    {
        var result = PreRequestScriptService.Run(
            "set_env('token', 'abc')\nlog(env.get('token', ''))\nset_env('timestamp', str(int(time.time())))",
            new Dictionary<string, string>());

        Assert.Equal("abc", result.Environment["token"]);
        Assert.True(long.TryParse(result.Environment["timestamp"], out _));
        Assert.Contains("abc", result.Logs);
    }

    [Fact]
    public void ScenarioRules_ExtractAndAssertResponse()
    {
        var response = new ApiResponseResult
        {
            StatusCode = 200,
            Body = "{\"data\":{\"token\":\"abc\",\"count\":2},\"ok\":true}",
            Headers = "Content-Type: application/json\r\nX-Request-Id: req-1",
        };

        var extracted = ScenarioRuleService.Extract(
            "token = json:$.data.token\nrequest_id = header:X-Request-Id",
            response);
        var assertions = ScenarioRuleService.Assert(
            "status == 200\nheader Content-Type contains json\njson $.data.count >= 1\njson $.ok == true",
            response);

        Assert.Equal("abc", extracted.Values["token"]);
        Assert.Equal("req-1", extracted.Values["request_id"]);
        Assert.True(assertions.Passed);
        Assert.All(assertions.Details, detail => Assert.StartsWith("PASS", detail));
    }

    [Fact]
    public void ScenarioReports_RedactSensitiveQueryValues()
    {
        var scenario = new ScenarioDefinition
        {
            Id = "s1",
            Name = "Smoke",
            Steps = [new ScenarioStepDefinition { Id = "step1", Name = "Login" }],
        };
        var results = new Dictionary<string, ScenarioStepResult>
        {
            ["step1"] = new()
            {
                Passed = true,
                Method = "GET",
                Url = "https://api.test/login?token=secret123&locale=en",
                StatusCode = 200,
            },
        };

        var html = ScenarioReportService.BuildHtml(scenario, "Default", results);
        var csv = ScenarioReportService.BuildCsv(scenario, results);
        var xml = ScenarioReportService.BuildJUnit(scenario, results);

        Assert.DoesNotContain("secret123", html + csv + xml);
        Assert.Contains("[REDACTED]", html);
        Assert.Contains("testsuite", xml);
    }

    [Fact]
    public void AiContext_RedactsHeadersBodyAndQuery()
    {
        var tab = new RequestTabSession
        {
            Method = "POST",
            Url = "https://api.test/orders?api_key=secret123",
            Body = "{\"password\":\"hidden\"}",
            Headers = [new HeaderEntry { Name = "Authorization", Value = "Bearer token123" }],
            Response = new ApiResponseResult
            {
                StatusCode = 401,
                Body = "{\"token\":\"response-secret\",\"error\":\"unauthorized\"}",
                Headers = "Set-Cookie: session=private",
            },
        };

        var context = new AiAnalysisService().BuildContext(tab);

        Assert.DoesNotContain("secret123", context);
        Assert.DoesNotContain("hidden", context);
        Assert.DoesNotContain("token123", context);
        Assert.DoesNotContain("response-secret", context);
        Assert.Contains("[REDACTED]", context);
    }

    [Fact]
    public async Task LegacyStore_RoundTripsCompatibleJsonFiles()
    {
        var directory = Path.Combine(Path.GetTempPath(), "curl-runner-tests-" + Guid.NewGuid().ToString("N"));
        try
        {
            var store = new LegacyStoreService(directory);
            await store.SaveHistoryAsync([new HistoryEntry { Method = "GET", Url = "https://api.test", Curl = "curl https://api.test" }]);
            await store.SaveCollectionsAsync(new Dictionary<string, List<SavedRequest>>
            {
                ["Smoke"] = [new SavedRequest { Name = "Health", Method = "GET", Curl = "curl https://api.test/health" }],
            });
            await store.SaveEnvironmentsAsync(new Dictionary<string, Dictionary<string, string>>
            {
                ["Default"] = new() { ["base_url"] = "https://api.test" },
            });

            Assert.Single(await store.LoadHistoryAsync());
            Assert.Single((await store.LoadCollectionsAsync())["Smoke"]);
            Assert.Equal("https://api.test", (await store.LoadEnvironmentsAsync())["Default"]["base_url"]);
        }
        finally
        {
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }
}
