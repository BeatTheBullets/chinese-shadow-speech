<h1 align="center">chinese-shadow-speech</h1>

<p align="center">
  <b>Practise speaking Mandarin by shadowing real Chinese videos, with feedback on every tone and sound.</b><br>
  Runs on your own computer. Free and open source.
</p>

<p align="center">
  <a href="https://github.com/BeatTheBullets/chinese-shadow-speech/releases/latest"><b>Download for Windows</b></a>
  &nbsp;·&nbsp; <a href="docs/user-guide.md">User guide</a>
  &nbsp;·&nbsp; <a href="docs/development.md">Run from source</a>
</p>

![Flow mode: the sentence fills with colour in time with the speaker](docs/screenshots/flow-listen.png)

Paste a YouTube link, and a few minutes later the video is a lesson: cut into short sentences, with pinyin, every
character aligned to the audio. Then you listen and repeat, sentence by sentence or a whole passage at a time, and the
app tells you which tones and sounds you got right.

## What you can do

- **Make lessons from YouTube or your own files.** Chinese subtitles are used when the video has real ones; otherwise
  the speech recogniser writes the text.
- **Practise two ways.** **Echo**: one sentence at a time, listen then repeat. **Flow**: shadow a whole passage, after the
  speaker or along with them.
- **See what went wrong.** Every syllable gets a tone verdict (`3→2` shows what you said instead), wrong initials and
  finals are pointed out, and pitch lines show your melody against the speaker's.
- **Hear yourself back.** Every take is kept; play the original and your take back to back.
- **Train your weak spots.** Stats show your weakest tones, tone pairs, sounds and characters, and **Drills** build a
  short session from all your lessons around one of them.
- **Review with Anki.** Practised sentences become listening cards in one click.
- **Look words up.** The text works with the [Yomitan](https://github.com/yomidevs/yomitan) pop-up dictionary.

| Echo: listen, then repeat | Flow: your turn |
|---|---|
| ![Echo mode with the tone and sound verdicts of the last take](docs/screenshots/echo-listen.png) | ![Flow mode: the bar shrinks while you speak](docs/screenshots/flow-turn.png) |
| **Stats: your weakest tones, sounds and characters** | **Library: lessons grouped by channel** |
| ![Stats overview](docs/screenshots/stats.png) | ![Library](docs/screenshots/library.png) |

<details>
<summary>More screenshots</summary>

| | |
|---|---|
| ![Echo: your turn](docs/screenshots/echo-record.png) | ![Flow setup with the last run ready to replay](docs/screenshots/flow-setup.png) |
| ![Send what you practised to Anki](docs/screenshots/export-dialog.png) | ![Review: flagged sentences and sentences not yet in Anki](docs/screenshots/review.png) |
| ![The help overlay](docs/screenshots/help.png) | ![Settings](docs/screenshots/settings.png) |

</details>

> Screenshots show lessons made from Mandarin Click's HSK1 stories.

## Install on Windows

1. Download `chinese-shadow-speech-<version>-setup.exe` from the
   [latest release](https://github.com/BeatTheBullets/chinese-shadow-speech/releases/latest).
2. Run it. The installer isn't code-signed yet, so Windows may say "Windows protected your PC": click **More info**,
   then **Run anyway**. It installs for your user only, without administrator rights.
3. The first start sets up the app and downloads the speech models (about 5 GB), which takes 10 to 20 minutes. A page
   in your browser shows the progress. Later starts take a few seconds.
4. The Library opens. Paste a YouTube link to make your first lesson.

**Needs:** Windows 10 or 11 (64-bit), 8 GB of RAM, 8 GB of free disk space, and an internet connection for the first
start and for YouTube. No graphics card needed.

The app keeps running in the notification area after you close the browser tab; use its icon to open it again or to
quit. Updates, your data and uninstalling: see [Your data on Windows](docs/user-guide.md#your-data-on-windows).

On Linux, or to work on the code, see [Run from source](docs/development.md).

## Privacy

Everything runs on your computer: the speech models, your recordings and your scores never leave it. The app goes
online only to download videos you ask for, to download the speech models once, to keep the YouTube downloader (yt-dlp)
up to date, and to check GitHub for a newer version.

## Roadmap

- **Next:** testing on more laptops, including long videos; lessons from **Bilibili** links and **podcast** feeds.
- **Later:** a Microsoft Store version; a signed installer.

Ideas and bug reports are welcome as [issues](https://github.com/BeatTheBullets/chinese-shadow-speech/issues).

## Documentation

- [User guide](docs/user-guide.md): every page and feature, keyboard shortcuts, Anki setup, your data on Windows.
- [Development](docs/development.md): run from source, tests, the Windows package, where things are in the code.
- [Configuration](docs/running.md): `config.toml`, CPU-only use, Docker, YouTube cookies and yt-dlp.

## Licence

Free software under the [GNU Affero General Public License v3.0 or later](LICENSE): you may use, study, share and
change it; if you distribute a changed version, or run one as a service for others, share its source under the same
licence. The speech models it downloads have their own licences ([THIRD_PARTY.md](THIRD_PARTY.md)); the alignment model
is non-commercial (CC-BY-NC 4.0), so the app is for non-commercial use.
