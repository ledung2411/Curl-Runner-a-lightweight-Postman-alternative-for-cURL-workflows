using CurlRunner.WinUI.Models;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace CurlRunner.WinUI.Services;

public static partial class ScenarioReportService
{
    [GeneratedRegex(@"(?i)([?&](?:token|key|api_key|apikey|secret|password|auth|signature)=)[^&]*")]
    private static partial Regex SensitiveQueryPattern();

    public static string BuildHtml(
        ScenarioDefinition scenario,
        string environment,
        IReadOnlyDictionary<string, ScenarioStepResult> results)
    {
        var rows = BuildRows(scenario, results);
        var passed = rows.Count(row => row.Result?.Passed == true);
        var failed = rows.Count(row => row.Result is { Passed: false, Skipped: false });
        var skipped = rows.Count(row => row.Result?.Skipped != false);
        var body = string.Join(Environment.NewLine, rows.Select(row =>
        {
            var result = row.Result;
            var outcome = result is null || result.Skipped ? "SKIP" : result.Passed ? "PASS" : "FAIL";
            var detail = result is null ? "" : string.Join("<br>", result.AssertionDetails.Select(WebUtility.HtmlEncode));
            if (detail.Length == 0 && result?.Error.Length > 0) detail = WebUtility.HtmlEncode(result.Error);
            return $"<tr><td>{row.Order}</td><td>{WebUtility.HtmlEncode(row.Step.Name)}</td><td>{WebUtility.HtmlEncode(result?.Method ?? "")}</td>" +
                   $"<td>{WebUtility.HtmlEncode(RedactUrl(result?.Url ?? ""))}</td><td>{WebUtility.HtmlEncode(result?.StatusCode.ToString() ?? "")}</td>" +
                   $"<td>{result?.ElapsedMilliseconds ?? 0}</td><td class='{outcome.ToLowerInvariant()}'>{outcome}</td><td>{detail}</td></tr>";
        }));
        return $$"""
<!doctype html><html><head><meta charset="utf-8"><title>{{WebUtility.HtmlEncode(scenario.Name)}}</title>
<style>body{font-family:Segoe UI,Arial;margin:32px;color:#1f2937}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d8dee9;padding:8px;text-align:left}th{background:#f3f4f6}.pass{color:#087f5b}.fail{color:#c92a2a}.skip{color:#667085}</style></head>
<body><h1>{{WebUtility.HtmlEncode(scenario.Name)}}</h1><p>Environment: {{WebUtility.HtmlEncode(environment)}} | Passed: {{passed}} | Failed: {{failed}} | Skipped: {{skipped}}</p>
<table><thead><tr><th>#</th><th>Step</th><th>Method</th><th>URL</th><th>Status</th><th>Time ms</th><th>Result</th><th>Details</th></tr></thead><tbody>{{body}}</tbody></table></body></html>
""";
    }

    public static string BuildCsv(ScenarioDefinition scenario, IReadOnlyDictionary<string, ScenarioStepResult> results)
    {
        var builder = new StringBuilder("order,name,method,url,status,elapsed_ms,result,assertions,error\r\n");
        foreach (var row in BuildRows(scenario, results))
        {
            var result = row.Result;
            var outcome = result is null || result.Skipped ? "SKIP" : result.Passed ? "PASS" : "FAIL";
            builder.AppendLine(string.Join(',', new[]
            {
                row.Order.ToString(), Csv(row.Step.Name), Csv(result?.Method ?? ""), Csv(RedactUrl(result?.Url ?? "")),
                (result?.StatusCode ?? 0).ToString(), (result?.ElapsedMilliseconds ?? 0).ToString(), outcome,
                Csv(string.Join(" | ", result?.AssertionDetails ?? [])), Csv(result?.Error ?? ""),
            }));
        }
        return builder.ToString();
    }

    public static string BuildJUnit(ScenarioDefinition scenario, IReadOnlyDictionary<string, ScenarioStepResult> results)
    {
        var rows = BuildRows(scenario, results);
        var suite = new XElement("testsuite",
            new XAttribute("name", scenario.Name),
            new XAttribute("tests", rows.Count),
            new XAttribute("failures", rows.Count(row => row.Result is { Passed: false, Skipped: false })),
            new XAttribute("skipped", rows.Count(row => row.Result?.Skipped != false)));
        foreach (var row in rows)
        {
            var result = row.Result;
            var test = new XElement("testcase",
                new XAttribute("name", row.Step.Name),
                new XAttribute("classname", scenario.Name),
                new XAttribute("time", (result?.ElapsedMilliseconds ?? 0) / 1000d));
            if (result is null || result.Skipped)
            {
                test.Add(new XElement("skipped"));
            }
            else if (!result.Passed)
            {
                test.Add(new XElement("failure",
                    new XAttribute("message", result.Error.Length > 0 ? result.Error : "Assertion failed"),
                    string.Join(Environment.NewLine, result.AssertionDetails)));
            }
            test.Add(new XElement("system-out", $"{result?.Method} {RedactUrl(result?.Url ?? "")}"));
            suite.Add(test);
        }
        return new XDocument(new XDeclaration("1.0", "utf-8", null), suite).ToString();
    }

    private static List<(int Order, ScenarioStepDefinition Step, ScenarioStepResult? Result)> BuildRows(
        ScenarioDefinition scenario,
        IReadOnlyDictionary<string, ScenarioStepResult> results) =>
        scenario.Steps.Select((step, index) =>
            (index + 1, step, results.TryGetValue(step.Id, out var result) ? result : null)).ToList();

    private static string RedactUrl(string value) => SensitiveQueryPattern().Replace(value, "$1[REDACTED]");
    private static string Csv(string value) => $"\"{(value ?? "").Replace("\"", "\"\"")}\"";
}
