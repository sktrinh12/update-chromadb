import os
import json
from datetime import datetime, timedelta
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication

# Configuration
AZURE_DEVOPS_ORG = os.environ['AZURE_DEVOPS_ORG']
AZURE_DEVOPS_PROJECT = os.environ['AZURE_DEVOPS_PROJECT']
AZURE_DEVOPS_PAT = os.environ['AZURE_DEVOPS_PAT']
INITIAL_EXPORT_DATE = os.environ.get('INITIAL_EXPORT_DATE', '2025-10-02')

def get_last_sync_time():
    """Get sync date - either yesterday or from initial export date"""
    initial_date = datetime.fromisoformat(INITIAL_EXPORT_DATE)
    yesterday = datetime.now() - timedelta(days=1)
    
    # Use initial export date as the baseline
    return initial_date if datetime.now() < initial_date + timedelta(days=2) else yesterday

def get_updated_work_items(since_date):
    """Fetch work items and their comments modified since the given date"""
    print(f"Fetching work items updated since: {since_date}")
    
    credentials = BasicAuthentication('', AZURE_DEVOPS_PAT)
    connection = Connection(
        base_url=f'https://dev.azure.com/{AZURE_DEVOPS_ORG}',
        creds=credentials
    )
    
    wit_client = connection.clients.get_work_item_tracking_client()
    
    # WIQL query to get work items changed since last sync
    wiql = {
        "query": f"""
        SELECT [System.Id], [System.Title], [System.State], [System.ChangedDate]
        FROM WorkItems
        WHERE [System.TeamProject] = '{AZURE_DEVOPS_PROJECT}'
        AND [System.ChangedDate] >= '{since_date.strftime('%Y-%m-%d')}'
        ORDER BY [System.ChangedDate] DESC
        """
    }
    
    results = wit_client.query_by_wiql(wiql)
    work_item_ids = [item.id for item in results.work_items]
    
    print(f"Found {len(work_item_ids)} updated work items")
    
    if not work_item_ids:
        return []
    
    # Fetch full work item details with comments
    work_items_data = []
    for wid in work_item_ids:
        work_item = wit_client.get_work_item(wid, expand='All')
        
        # Get comments for this work item
        comments = wit_client.get_comments(AZURE_DEVOPS_PROJECT, wid)
        
        work_items_data.append({
            'work_item': work_item,
            'comments': comments.comments if hasattr(comments, 'comments') else []
        })
    
    return work_items_data

def format_work_item_json(work_item_data):
    """Format work item and comments into the same structure as your export"""
    work_item = work_item_data['work_item']
    comments = work_item_data['comments']
    fields = work_item.fields
    
    # Format work item itself
    formatted_data = {
        'id': work_item.id,
        'title': fields.get('System.Title', ''),
        'type': fields.get('System.WorkItemType', ''),
        'state': fields.get('System.State', ''),
        'description': fields.get('System.Description', ''),
        'acceptanceCriteria': fields.get('Microsoft.VSTS.Common.AcceptanceCriteria', ''),
        'assignedTo': fields.get('System.AssignedTo', {}).get('displayName', '') if isinstance(fields.get('System.AssignedTo'), dict) else '',
        'createdDate': fields.get('System.CreatedDate', ''),
        'changedDate': fields.get('System.ChangedDate', ''),
        'areaPath': fields.get('System.AreaPath', ''),
        'iterationPath': fields.get('System.IterationPath', ''),
        'tags': fields.get('System.Tags', ''),
        'comments': []
    }
    
    # Add comments in the same structure as your export
    for comment in comments:
        formatted_data['comments'].append({
            'workItemId': work_item.id,
            'id': comment.id,
            'version': getattr(comment, 'version', 1),
            'text': comment.text,
            'createdBy': {
                'displayName': comment.created_by.display_name if hasattr(comment, 'created_by') else '',
                'uniqueName': getattr(comment.created_by, 'unique_name', '') if hasattr(comment, 'created_by') else '',
            },
            'createdDate': comment.created_date.isoformat() if hasattr(comment, 'created_date') else '',
            'modifiedBy': {
                'displayName': comment.modified_by.display_name if hasattr(comment, 'modified_by') else '',
                'uniqueName': getattr(comment.modified_by, 'unique_name', '') if hasattr(comment, 'modified_by') else '',
            },
            'modifiedDate': comment.modified_date.isoformat() if hasattr(comment, 'modified_date') else '',
        })
    
    return formatted_data

def main():
    print("=" * 60)
    print("Azure DevOps API Test - Fetch Updated Work Items")
    print("=" * 60)
    
    # Get last sync time
    last_sync = get_last_sync_time()
    print(f"Fetching work items since: {last_sync.strftime('%Y-%m-%d')}")
    
    # Fetch updated work items from Azure DevOps
    work_items_data = get_updated_work_items(last_sync)
    
    if not work_items_data:
        print("No work items to update. Exiting.")
        return
    
    # Format all work items
    formatted_items = []
    for item in work_items_data:
        formatted = format_work_item_json(item)
        formatted_items.append(formatted)
    
    # Save to JSON file
    output_file = f"workitems_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(formatted_items, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Exported {len(formatted_items)} work items to {output_file}")
    print(f"\nSample of first item:")
    if formatted_items:
        sample = formatted_items[0]
        print(f"  ID: {sample['id']}")
        print(f"  Title: {sample['title']}")
        print(f"  Type: {sample['type']}")
        print(f"  State: {sample['state']}")
        print(f"  Comments: {len(sample['comments'])}")
    
    print("=" * 60)
    print("Test completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    main()
