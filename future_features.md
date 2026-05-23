# Future Features

## Planned

### Placeholder fill reminder
Notify the student when placeholder reflections are due to be filled.
Trigger: scheduled job checks queue, sends system notification or shows badge in UI.

### Custom AI system prompt (per school)
Different schools have different CAS reflection/proposal format requirements.
Add a text area in Settings where the student can edit the system prompt used for AI generation.
The custom prompt is stored in `cas_config.json` and injected into every AI call.

## Deferred

### Draft mode
Save a reflection locally before submitting to ManageBac.
Deferred: low urgency, adds complexity to sync logic.
