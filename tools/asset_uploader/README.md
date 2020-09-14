# RiiTag-RPC Asset Uploader

This tool will automatically download game covers from GameTDB and
either save them locally or upload them to a Discord application for use
in a rich presence.

It requires you to set various options in the file itself before running.
These are documented using comments in the same file. If an option is undocumented,
~~learn how to use your fucking brain~~ it is probably self explanatory enough.

The input file is expected to contain the play count and game ID for every game separated
by a space, each on a new line. Example:
```
143 RMCP01
87 RUUE01
54 RSBE01
```
