from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.routers.dependencies import store_dependency
from app.services.actions import approve_actions, execute_action, reject_actions
from app.services.store import FireGuardStore

router = APIRouter(tags=["actions"])


def _actions_for_bundle(store: FireGuardStore, bundle_id: str) -> list[dict]:
    return [action for action in store.list("action_logs") if action["bundle_id"] == bundle_id]


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    approval = store.get("approval_requests", approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    actions = _actions_for_bundle(store, approval["bundle_id"])
    updated_actions, updated_approval = approve_actions(actions, approval)
    for action in updated_actions:
        store.upsert("action_logs", action["action_id"], action)
    store.upsert("approval_requests", approval_id, updated_approval)
    return {"approval": updated_approval, "actions": updated_actions}


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, store: FireGuardStore = Depends(store_dependency)) -> dict:
    approval = store.get("approval_requests", approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    actions = _actions_for_bundle(store, approval["bundle_id"])
    updated_actions, updated_approval = reject_actions(actions, approval)
    for action in updated_actions:
        store.upsert("action_logs", action["action_id"], action)
    store.upsert("approval_requests", approval_id, updated_approval)
    return {"approval": updated_approval, "actions": updated_actions}


@router.post("/actions/{bundle_id}/execute")
def execute(bundle_id: str, settings: Settings = Depends(get_settings), store: FireGuardStore = Depends(store_dependency)) -> dict:
    actions = _actions_for_bundle(store, bundle_id)
    if not actions:
        raise HTTPException(status_code=404, detail="Action bundle not found")
    residents = store.list("resident_contacts")
    executed = []
    failed = []
    for action in actions:
        updated = execute_action(action, settings, residents)
        store.upsert("action_logs", updated["action_id"], updated)
        if updated["status"] == "executed":
            executed.append(updated)
        else:
            failed.append(updated)
    return {"bundle_id": bundle_id, "executed": executed, "failed": failed}
