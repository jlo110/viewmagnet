# ViewMagnet Chrome Extension

Analyze YouTube videos directly from your browser. Get ML-powered predictions and optimization tips.

## Features

- 🔮 **Score Badge**: Shows prediction score on every YouTube video page
- 📊 **Component Breakdown**: Title, thumbnail, and channel scores
- 💡 **Key Factors**: What's helping or hurting the video
- 🎯 **Recommendations**: Actionable tips for improvement

## Installation

### For Development

1. Open Chrome and go to `chrome://extensions/`
2. Enable "Developer mode" (top right toggle)
3. Click "Load unpacked"
4. Select the `chrome-extension` folder

### Icons Required

You need to add icon files to the `icons/` folder:
- `icon16.png` (16x16)
- `icon32.png` (32x32)
- `icon48.png` (48x48)
- `icon128.png` (128x128)

You can generate these from any 128x128 image.

## Requirements

The extension requires the ViewMagnet API to be running locally:

```bash
cd /path/to/ViewMagnet
source venv312/bin/activate
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

## Usage

1. Navigate to any YouTube video
2. Click the ViewMagnet extension icon to see the analysis
3. Or view the score badge that appears on the video page

## Files

| File | Description |
|------|-------------|
| `manifest.json` | Extension configuration (Manifest V3) |
| `popup.html/css/js` | Extension popup UI |
| `content.js/css` | YouTube page overlay |
| `background.js` | Service worker for API calls |

## Development

### Building for Production

1. Update version in `manifest.json`
2. Zip the extension folder
3. Upload to Chrome Web Store

### Connecting to Production API

Update the `API_BASE` constant in:
- `popup.js`
- `content.js`
- `background.js`

Change from `http://localhost:8000` to your production API URL.

## Troubleshooting

**"Cannot connect to ViewMagnet API"**
- Make sure the FastAPI server is running on port 8000
- Check that CORS is enabled for the extension

**Score not appearing on YouTube**
- Refresh the page
- Check if the extension has permission for youtube.com
- Look for errors in the browser console

**Extension not loading**
- Make sure all files are present
- Check for syntax errors in the console
- Verify manifest.json is valid JSON




