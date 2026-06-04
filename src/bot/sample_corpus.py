"""
Canonical sample documents for the RAG index.

Used in two places:
  - scripts/upload_sample_docs.py seeds these into the real Azure AI Search index.
  - search_client.py uses them as the in-memory corpus when APP_MODE=local.

Each document carries an ACL (`allowedGroups` / `allowedUsers`) so security trimming
is demonstrable: alice (grp-engineering, grp-allstaff) and bob (grp-sales,
grp-allstaff) see different subsets — see graph_client.LOCAL_DIRECTORY.
"""

SAMPLE_DOCS: list[dict] = [
    {
        "id": "doc-deploy-runbook",
        "title": "Deployment Runbook",
        "content": (
            "To deploy ATLAS-RAG, run `azd provision` then `azd deploy`. The bot runs "
            "on Azure App Service via uvicorn. Roll back by redeploying the previous "
            "revision. The deploy process is owned by the engineering team."
        ),
        "source_url": "https://contoso.sharepoint.com/sites/eng/Runbook.aspx",
        "allowedGroups": ["grp-engineering"],
        "allowedUsers": [],
    },
    {
        "id": "doc-sales-playbook",
        "title": "Sales Playbook Q3",
        "content": (
            "Q3 sales targets focus on enterprise renewals. The pipeline review cadence "
            "is weekly. Discounting above 15% requires director approval."
        ),
        "source_url": "https://contoso.sharepoint.com/sites/sales/Playbook.aspx",
        "allowedGroups": ["grp-sales"],
        "allowedUsers": [],
    },
    {
        "id": "doc-holiday-schedule",
        "title": "Company Holiday Schedule",
        "content": (
            "The company observes 11 paid holidays. The office is closed the last week "
            "of December. Submit time-off requests through the HR portal."
        ),
        "source_url": "https://contoso.sharepoint.com/sites/hr/Holidays.aspx",
        "allowedGroups": ["grp-allstaff"],
        "allowedUsers": [],
    },
    {
        "id": "doc-eng-oncall",
        "title": "Engineering On-Call Guide",
        "content": (
            "On-call engineers acknowledge pages within 15 minutes. Escalate Sev1 "
            "incidents to the incident commander. The deploy freeze applies during Sev1."
        ),
        "source_url": "https://contoso.sharepoint.com/sites/eng/OnCall.aspx",
        "allowedGroups": ["grp-engineering"],
        "allowedUsers": [],
    },
]
