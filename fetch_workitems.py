import os
import requests
import json
from datetime import datetime, timedelta
from typing import Iterable, List, Union

ORG_NAME = os.getenv("AZURE_DEVOPS_ORG")
PROJECT_NAME = os.getenv("AZURE_DEVOPS_PROJECT")
API_BASE = f"https://dev.azure.com/{ORG_NAME}/{PROJECT_NAME}/_apis"
API_VERSION = "7.0"

PAT = os.getenv("AZURE_DEVOPS_PAT")
if not PAT:
    raise RuntimeError("Please set AZURE_DEVOPS_PAT in env")

SESSION = requests.Session()
SESSION.auth = ("", PAT)
SESSION.headers.update({"Content-Type": "application/json"})

MAX_IDS_PER_BATCH = 200


def run_wiql(query: str) -> dict:
    url = f"{API_BASE}/wit/wiql?api-version={API_VERSION}"
    r = SESSION.post(url, json={"query": query})
    r.raise_for_status() 
    return r.json()


def _ensure_id_list(ids_or_id: Union[int, str, Iterable[int]]) -> List[int]:
    if isinstance(ids_or_id, (int, str)):
        return [int(ids_or_id)]
    if hasattr(ids_or_id, "__iter__"):
        return [int(i) for i in ids_or_id]
    raise TypeError("ids_or_id must be int or iterable of ints")


def _chunks(lst: List[int], n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]


def get_work_item_details(ids_or_id: Union[int, Iterable[int]]) -> List[dict]:
    """
    Returns a list of work item JSON blobs. Accepts a single id or a list.
    Will chunk large lists into batches (<= MAX_IDS_PER_BATCH).
    Expands 'relations'.
    """
    ids = _ensure_id_list(ids_or_id)
    all_values = []
    for chunk in _chunks(ids, MAX_IDS_PER_BATCH):
        params = {
            "ids": ",".join(map(str, chunk)),
            "$expand": "relations",
            "api-version": API_VERSION,
        }
        url = f"{API_BASE}/wit/workitems"
        r = SESSION.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        all_values.extend(data.get("value", []))
    return all_values


def get_comments(item_id: int) -> list:
    """
    Fetches all comments for a work item using the comments API (requires preview API version).
    Uses continuationToken from the response body to page through results.
    """
    url = f"{API_BASE}/wit/workItems/{item_id}/comments"
    params = {
        "api-version": "7.1-preview.4",
        "$top": 100
    }
    all_comments = []
    while True:
        r = SESSION.get(url, params=params)
        try:
            r.raise_for_status()
        except requests.HTTPError:
            print(f"Warning: Failed to fetch comments for {item_id}: {r.status_code}")
            break

        data = r.json()
        all_comments.extend(data.get("comments", []))

        token = data.get("continuationToken")
        if token:
            params["continuationToken"] = token
        else:
            break

    return all_comments


def fetch_linked_commit_if_any(rel_url: str) -> dict:
    """
    If a relation URL looks like a Git commit artifact, fetch it.
    """
    if "/_apis/git/repositories/" in rel_url and "/commits/" in rel_url:
        r = SESSION.get(rel_url, params={"api-version": API_VERSION})
        if r.ok:
            return r.json()
    return {}


if __name__ == "__main__":
    print("=" * 70)
    print("Azure DevOps Work Items Export")
    print("=" * 70)
    
    # Get the sync date based on previous exports
    last_date = os.getenv("FILTERED_DATE")

    # subtract a buffer window (7 days)
    since_date = datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=7)
    since_date = since_date.strftime("%Y-%m-%d")
    
    # Build WIQL query with date filter
    WIQL = f"""
    SELECT [System.Id], [System.Title], [System.ChangedDate]
    FROM WorkItems
    WHERE [System.TeamProject] = '{PROJECT_NAME}'
    AND [System.ChangedDate] >= '{since_date}'
    ORDER BY [System.ChangedDate] DESC
    """
    
    print(f"\nExecuting WIQL query...\n{WIQL}")
    wiql_res = run_wiql(WIQL)
    ids = [w["id"] for w in wiql_res.get("workItems", [])]
    print(f"Found {len(ids)} work items to process")

    if not ids:
        print("\n✓ No new work items to update. Exiting.")
        exit(0)

    work_items = get_work_item_details(ids)
    print(f"Retrieved details for {len(work_items)} work items")

    # Assemble records
    records = []
    for i, wi in enumerate(work_items, 1):
        item_id = wi["id"]
        fields = wi.get("fields", {})
        relations = wi.get("relations", [])
        
        # Classify relations
        parents, children, commits, other_rels = [], [], [], []
        for r in relations:
            attrs = r.get("attributes", {}) or {}
            name = (attrs.get("name") or "").lower()
            url = r.get("url")
            if "parent" in name:
                parents.append(url)
            elif "child" in name:
                children.append(url)
            elif url and ("/_apis/git/repositories/" in url and "/commits/" in url or "commit" in name or "fixed in" in name.lower()):
                commits.append(url)
            else:
                other_rels.append({"rel": r.get("rel"), "url": url, "attributes": attrs})

        # Fetch comments
        print(f"  [{i}/{len(work_items)}] Processing work item {item_id}...", end="")
        comments = get_comments(item_id)
        print(f" {len(comments)} comments")
        
        # Fetch commit details
        commit_details = [fetch_linked_commit_if_any(curl) for curl in commits]
        wi_type = fields.get("System.WorkItemType", "")  # "Bug" or "User Story"

        # Prefer normal description if it exists
        description = fields.get("System.Description") or ""

        # For Bugs (or items without description), fall back to Repro Steps + System Info
        if not description:
            repro = fields.get("Microsoft.VSTS.TCM.ReproSteps") or ""
            sysinfo = fields.get("Microsoft.VSTS.TCM.SystemInfo") or ""
            # Only build a synthetic description if there is actual content
            bug_parts = []
            if repro:
                bug_parts.append(f"Repro Steps:\n{repro}")
            if sysinfo:
                bug_parts.append(f"System Info:\n{sysinfo}")
            if bug_parts:
                description = "\n\n".join(bug_parts)

        record = {
            "id": item_id,
            "title": fields.get("System.Title"),
            "description": description,
            "acceptance_criteria": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""),
            "tags": fields.get("System.Tags", ""),
            "story_points": fields.get("Microsoft.VSTS.Scheduling.StoryPoints", None),
            "type": fields.get("System.WorkItemType"),
            "state": fields.get("System.State"),
            "assignedTo": (fields.get("System.AssignedTo") or {}).get("displayName"),
            "createdDate": fields.get("System.CreatedDate"),
            "changedDate": fields.get("System.ChangedDate"),
            "areaPath": fields.get("System.AreaPath"),
            "iterationPath": fields.get("System.IterationPath"),
            "parents": parents,
            "children": children,
            "commit_links": commits,
            "commit_details": commit_details,
            "comments": comments,
            "raw": wi
        }
        records.append(record)

    # Save to JSON (TEMP)
    output_file = f"workitems_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Exported work items to {output_file}")

    # logic to upload newest records into chroma db

    print(f"\n✅ Saved {len(records)} work items to chromaDB")
    
    # Show sample
    if records:
        sample = records[0]
        print(f"\nSample work item:")
        print(f"  ID: {sample['id']}")
        print(f"  Title: {sample['title']}")
        print(f"  Type: {sample['type']}")
        print(f"  State: {sample['state']}")
        print(f"  Comments: {len(sample['comments'])}")
        print(f"  Commits: {len(sample['commit_links'])}")
    
    print("=" * 70)
    print("Export completed successfully!")
    print("=" * 70)

    if not records:
        print("NO_NEW_ITEMS=1")
    else:
        print("NO_NEW_ITEMS=0")
