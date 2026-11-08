# BDA Thai user guide

[Download the four-page PDF](AI-Accounts-User-Guide-BDA-TH.pdf).

The guide covers setup, provider-specific shared sessions, quota selection, confirmation before switching, reset controls, backups and troubleshooting. It distinguishes session sharing within one service on one computer from cross-provider or cross-device synchronization.

Rendered and visually checked on 8 November 2026. Sarabun Regular and Bold are embedded; PDF text extraction and four-page count verified. No personal account addresses, tokens or session transcripts are included.

To regenerate with approved local brand assets:

```sh
python -m pip install reportlab==5.1.0 uharfbuzz==0.57.0 pillow==13.0.0
python docs/manual/build_manual.py --fonts /path/to/Sarabun --logo /path/to/bda-logo.jpg --output docs/manual/AI-Accounts-User-Guide-BDA-TH.pdf
```

The font directory must contain `Sarabun-Regular.ttf` and `Sarabun-Bold.ttf`. The build requires the BDA logo supplied separately. Runtime dependencies above are documentation-only, not additions to the application runtime.

The PDF describes Beta behavior and includes limitations. It is not a declaration that every platform feature has passed live testing.
