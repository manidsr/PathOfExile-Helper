# Path of Exile Helper

A Windows desktop workspace for Auto Sender and Auto Crafter.

## Run on Windows

From a checkout with Python 3.12 installed:

    py -3.12 -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
    .venv\Scripts\python main.pyw

To build the executable locally, run `build.bat`. Open `dist\PathOfExileHelper\PathOfExileHelper.exe` and keep its supporting folder beside it. The Windows desktop build workflow also packages the folder as the **PathOfExileHelper-Windows** Actions artifact.

## Auto Sender

Invite your Discord bot to a server where you can post. Give it View Channel and Send Messages in the destination channel. Paste the channel ID and bot token into Delivery. You can also supply the token through the POE_SENDER_BOT_TOKEN environment variable.

Write your message or import the old message.txt. Formatting and the final line are preserved. Send once or select Repeat message and an interval in minutes. A schedule starts immediately. Stop cancels future deliveries. A request already in flight can complete. Closing the application ends the schedule. Draft text, channel and interval are saved locally on send and exit. The token stays in memory.

## Auto Crafter

The existing license and trial system uses a separate, operator-owned Discord bot. On your own machine, configure the following environment variables before starting the app:

| Variable | Value |
| --- | --- |
| POE_LICENSE_BOT_TOKEN | Token of the licensing bot |
| POE_LICENSE_AVAILABLE_CHANNEL_ID | Private channel containing available keys |
| POE_LICENSE_ACTIVATED_CHANNEL_ID | Private channel containing activations |

The licensing bot requires message content access and permission to view, read history, post and manage messages in its two licensing channels. Keep these operator credentials private. Public-client distribution of licensed crafting requires a separate server-side activation service.

Open Auto Crafter and activate your existing key. In Settings, set the scan region, then capture the lit and unlit states in Calibrate Color. The Crafter tab controls the countdown, mode, start and stop. The Regex Vault supports importing, exporting and organizing presets. Opening Auto Sender stops crafting and releases the crafting hotkeys for editing.

Existing crafter settings, licenses, and presets use the original %APPDATA%\AutoCrafter directory. The sender draft is saved alongside them in sender-draft.json.
