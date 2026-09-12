"""Account-scoped connection to the configured Ambiguous workspace."""
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import select
from app.api.dependencies import db_session, user
from app.domain.models import Account, Action, Memory, RawCapture, User, now
from app.repositories.memories import owned
from app.integrations.ambiguous_client import AmbiguousClient
from app.services.event_service import timestamp

router = APIRouter(prefix='/api/integrations/ambiguous')


from app.services.ambiguous_sync import require_owner, sync_memory


@router.get('/status')
def status(request: Request, db=Depends(db_session), user_id=Depends(user)):
    config = request.app.state.config
    require_owner(config, db, user_id)
    try:
        with AmbiguousClient(config.ambiguous_api_key) as client:
            identity = client.call('auth_whoami')
        return {'connected':True, 'workspace_id':identity.get('workspace_id'),
                'calendar_id':config.ambiguous_calendar_id}
    except Exception:
        raise HTTPException(502, 'Could not reach Ambiguous. Check the connection.')


@router.post('/memories/{memory_id}/sync')
def sync(memory_id: str, request: Request, db=Depends(db_session), user_id=Depends(user)):
    return sync_memory(db, user_id, memory_id, request.app.state.config)
