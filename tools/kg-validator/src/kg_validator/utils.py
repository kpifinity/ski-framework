"""
Utility functions for KG Validator
"""

import json
import os
from typing import List, Dict, Any
from .models import ComplianceRule


def load_rules(file_path: str) -> List[ComplianceRule]:
    """
    Load rules from JSON file (output of kg-extractor)

    Args:
        file_path: Path to JSON file with extracted rules

    Returns:
        List of ComplianceRule objects
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Rules file not found: {file_path}")

    with open(file_path, "r") as f:
        data = json.load(f)

    rules = []

    # Handle both direct rule array and kg-extractor output format
    rule_data = data.get("rules", data) if isinstance(data, dict) else data

    for rule_dict in rule_data:
        try:
            rule = ComplianceRule(**rule_dict)
            rules.append(rule)
        except Exception as e:
            print(f"Warning: Failed to load rule: {str(e)}")

    return rules


def save_validation_result(result: Any, file_path: str) -> None:
    """
    Save validation result to JSON file

    Args:
        result: ValidationResult object
        file_path: Path to save JSON file
    """
    with open(file_path, "w") as f:
        json.dump(result.to_json(), f, indent=2)


def validate_rule_fields(rule: ComplianceRule) -> List[str]:
    """
    Check for missing required fields in a rule

    Args:
        rule: Rule to validate

    Returns:
        List of missing field names
    """
    required_fields = [
        "id",
        "subject",
        "relation",
        "object",
        "source_document",
        "source_clause",
        "confidence",
        "reasoning",
    ]

    missing = []
    for field in required_fields:
        value = getattr(rule, field, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)

    return missing


def generate_html_report(result: Any, output_path: str) -> None:
    """
    Generate HTML validation report

    Args:
        result: ValidationResult object
        output_path: Path to save HTML file
    """
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>SKI Framework - Validation Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        .stat {{ display: inline-block; margin-right: 30px; }}
        .stat-number {{ font-size: 24px; font-weight: bold; color: #0066cc; }}
        .stat-label {{ font-size: 12px; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #f0f0f0; font-weight: bold; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        .approved {{ color: green; }}
        .rejected {{ color: red; }}
        .flagged {{ color: orange; }}
        .issue {{ background: #fff3cd; padding: 10px; margin: 10px 0; border-left: 4px solid #ffc107; }}
        .conflict {{ background: #f8d7da; padding: 10px; margin: 10px 0; border-left: 4px solid #dc3545; }}
    </style>
</head>
<body>
    <h1>SKI Framework - Validation Report</h1>
    <div class="summary">
        <div class="stat">
            <div class="stat-number">{result.metadata.total_rules_reviewed}</div>
            <div class="stat-label">Total Rules Reviewed</div>
        </div>
        <div class="stat">
            <div class="stat-number approved">{result.metadata.total_approved}</div>
            <div class="stat-label">Approved</div>
        </div>
        <div class="stat">
            <div class="stat-number rejected">{result.metadata.total_rejected}</div>
            <div class="stat-label">Rejected</div>
        </div>
        <div class="stat">
            <div class="stat-number flagged">{result.metadata.total_flagged}</div>
            <div class="stat-label">Flagged</div>
        </div>
    </div>

    <h2>Approved Rules ({len(result.approved_rules)})</h2>
    <table>
        <tr>
            <th>ID</th>
            <th>Subject</th>
            <th>Relation</th>
            <th>Object</th>
            <th>Source</th>
            <th>Validator Notes</th>
        </tr>
"""

    for rule in result.approved_rules:
        html += f"""        <tr>
            <td>{rule.id}</td>
            <td>{rule.subject}</td>
            <td>{rule.relation}</td>
            <td>{rule.object}</td>
            <td>{rule.source_document} ({rule.source_clause})</td>
            <td>{rule.validator_notes or ''}</td>
        </tr>
"""

    html += """    </table>

    <h2>Issues Found ({})""".format(len(result.issues))
    html += """</h2>
"""

    for issue in result.issues:
        html += f"""    <div class="issue">
        <strong>Rule {issue.rule_id}: {issue.issue_type}</strong> [{issue.severity}]
        <br/>
        {issue.message}
"""
        if issue.suggested_action:
            html += f"        <br/><em>Suggested Action: {issue.suggested_action}</em>\n"
        html += "    </div>\n"

    if result.conflicts:
        html += f"""
    <h2>Conflicts Detected ({len(result.conflicts)})</h2>
"""
        for conflict in result.conflicts:
            html += f"""    <div class="conflict">
        <strong>Conflict between {conflict.rule_id_1} and {conflict.rule_id_2}</strong>
        <br/>
        Type: {conflict.conflict_type}
        <br/>
        {conflict.explanation}
    </div>
"""

    if result.duplicates:
        html += f"""
    <h2>Duplicates Detected ({len(result.duplicates)})</h2>
    <table>
        <tr>
            <th>Rule 1</th>
            <th>Rule 2</th>
            <th>Similarity</th>
            <th>Type</th>
        </tr>
"""
        for dup in result.duplicates:
            html += f"""        <tr>
            <td>{dup.rule_id_1}</td>
            <td>{dup.rule_id_2}</td>
            <td>{dup.similarity_score:.2%}</td>
            <td>{dup.duplicate_type}</td>
        </tr>
"""
        html += "    </table>\n"

    html += f"""
    <hr/>
    <small>
        Report generated: {result.metadata.validation_timestamp}
        <br/>
        Validation duration: {result.metadata.validation_duration_seconds:.2f} seconds
    </small>
</body>
</html>
"""

    with open(output_path, "w") as f:
        f.write(html)
