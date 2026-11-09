"""Bounded guard against automatic paid fallback under AI Accounts authority."""

def patch(text):
    if not isinstance(text,str):raise ValueError('Unknown continuation runtime')
    start_marker='def approved_route(candidates, kind, probes):'
    end_marker='\n\ndef tick('
    if text.count(start_marker)!=1:raise ValueError('Runtime changed; reconcile continuation before patching')
    start=text.index(start_marker)
    end=text.find(end_marker,start)
    if end<0:raise ValueError('Runtime changed; reconcile continuation before patching')
    block=text[start:end]
    old='    except ValueError:\n        pass\n'
    if block.count(old)!=1:raise ValueError('Runtime changed; continuation guard not applied')
    new="    except ValueError:\n        if getattr(pool, 'CONTROL_PLANE_VERSION', None) == 'ai_accounts_sticky_v1':\n            raise\n        pass\n"
    return text[:start]+block.replace(old,new,1)+text[end:]
