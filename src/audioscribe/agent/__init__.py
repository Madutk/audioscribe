"""KI-Analyse per Claude-Agent (PRD §16, FR-28..34).

Reine Logik (Skills, Material, Prompt, Schreibschutz, Manifest) liegt in eigenen
Modulen ohne SDK-Import; nur ``runner`` importiert ``claude_agent_sdk`` - und das
erst beim Aufruf, damit der Kern-CLI ohne das Extra ``agent`` lauffaehig bleibt.
"""
