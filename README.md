# Daily Govee light show

Gives the Front led lights (H805C) a different show every day: one color and one pattern. Once a
day, GitHub's free scheduler runs `daily_show.py`, which paints the lights through Govee's cloud,
so your computer can be off. Every 10 minutes the Power schedule workflow switches the lights
to match the schedule: on from sunset to midnight and from 4:30am to sunrise in Simi Valley,
with daylight saving handled. It doesn't need the Govee app's timers.

There are 30 shows in `SHOWS` in `daily_show.py`, and each one is used once before any repeats.
Scenes and DIY scenes aren't used, because they light the section that stays dark for the
neighbors.

Each evening, the Evening effects workflow animates the show from the first hourly run after
the lights come on until they go off at midnight. Solid shows pulse brighter and dimmer, and the
others drift along the roofline. Govee's cloud is slow and allows 10,000 requests a day, so the
effect sends one command every `COMMAND_SECONDS` seconds. The repository is public, because
GitHub's free time for private repositories only covers about 50 minutes a night.

The lights have 27 sections of about 4 boxes each. `DARK_SEGMENTS` sets how many stay off at the
start of the roofline. If the program can't set sections separately, it sends nothing.

## Good to know

- The show changes around 3 to 4pm Pacific, so a new one is ready at sunset. GitHub can run it
  up to an hour or so late.
- If the lights are off at that time, the program paints the show and switches them back off.
- `last-show.txt` records the most recent show.
- To run it by hand, go to **Actions > Daily light show > Run workflow**. Don't use **Re-run
  jobs** on an old run, because a re-run uses that run's old code.
- The key is stored only in the GitHub secret `GOVEE_API_KEY`.
