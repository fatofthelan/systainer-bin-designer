# Contributing

Bug reports, fit feedback and pull requests are welcome.

- **Fit problems:** say which organizer you have, your printer, nozzle and filament, and which fit values you changed.
- **Bugs:** include the message from the palette's status line and, if possible, the layout (*Saved layouts* are stored in `layouts.json` in the per-user data folder; see the README).
- **Code:** keep `palette/layout.js` and `sbd_layout.py` in sync, and run the tests before opening a pull request:

  ```
  python3 -m unittest discover -s tests -v
  ```

  Changes to `sbd_builder.py` should also pass `tests/fusion_smoke_test.py` inside Fusion.
