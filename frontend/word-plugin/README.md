# 📄 Word Plugin Setup & Deployment

## Overview

The Word plugin is an Office Add-in that provides a user-friendly interface to:
- Ingest documents into the RAG knowledge base
- Generate AI content using LLM + context retrieval
- Populate Word templates automatically

## Quick Start

### For Local Testing (Without Installation)

#### 1. Start the Backend Server
```bash
cd /Users/shubhamsaini/Desktop/Genai Project

# Activate virtual environment
source venv/bin/activate

# Start FastAPI server
python -m uvicorn backend.main:app --reload

# Server runs at http://localhost:8000
```

#### 2. Host the Plugin Files
You need to serve the plugin files over HTTPS (required by Office). For development:

**Option A: Using Python HTTP Server**
```bash
# In another terminal, from word-plugin folder
cd frontend/word-plugin

# Python 3
python -m http.server 3000

# Or using live-server (if installed)
live-server --port=3000
```

**Option B: Using Node.js**
```bash
npm install -g http-server
cd frontend/word-plugin
http-server -p 3000 -c-1
```

#### 3. Create a Test Manifest
For local testing, create `manifest_local.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1">
  <Id>12345678-1234-1234-1234-123456789012</Id>
  <Version>1.0.0.0</Version>
  <ProviderName>AI Document Generator</ProviderName>
  <DefaultLocale>en-US</DefaultLocale>
  <DisplayName DefaultValue="AI Document Generator"/>
  <Description DefaultValue="Generate and populate Word documents using AI and RAG"/>
  <Hosts>
    <Host Name="Document"/>
  </Hosts>
  <DefaultSettings>
    <SourceLocation DefaultValue="http://localhost:3000/taskpane.html"/>
  </DefaultSettings>
  <Permissions>ReadWriteDocument</Permissions>
</OfficeApp>
```

#### 4. Load Plugin in Word

**Windows:**
1. Open Word
2. File → Options → Trust Center → Trust Center Settings → Trusted Add-in Catalogs
3. Add: `http://localhost:3000/manifest_local.xml`
4. File → Insert → Get Add-ins → My Add-ins → Upload My Add-in
5. Select `manifest_local.xml`

**Mac:**
1. Open Word
2. Insert → Get Add-ins → My Add-ins
3. Click "Upload My Add-in"
4. Select `manifest_local.xml`

#### 5. Update Backend URL (if needed)
In the plugin UI, go to Settings and update:
```
Backend URL: http://localhost:8000
```

## File Structure

```
word-plugin/
├── manifest.xml              # Office Add-in configuration (production)
├── manifest_local.xml        # Local development manifest
├── taskpane.html            # Main UI
├── taskpane.css             # Styles
├── taskpane.js              # Main logic
├── office.js                # Office API wrapper
└── README.md                # This file
```

## Files Overview

### manifest.xml
- Configuration file for Office Add-in
- Defines permissions, URLs, and metadata
- Update `SourceLocation` to your server URL for production

### taskpane.html
- Clean, modern UI with 3 main tabs:
  - **Upload Document**: Ingest documents into RAG
  - **Generate Content**: Create AI content using prompts
  - **Populate Template**: Auto-fill Word placeholders

### taskpane.js
- Handles user interactions
- Makes API calls to FastAPI backend
- Manages placeholder detection and population
- Error handling and status messages

### office.js
- Initializes Office API
- Helper functions for API requests
- Configuration management
- Connection testing

### taskpane.css
- Modern gradient design
- Responsive layout
- Smooth animations
- Tab navigation
- Form styling

## UI Features

### 📤 Upload Document Tab
- Document name input
- Content textarea for pasting text
- Upload to RAG button
- Success/error feedback

### ✨ Generate Content Tab
- Prompt textarea
- Context retrieval count selector
- Generate button
- Display generated content
- Copy to clipboard button

### 📋 Populate Template Tab
- Find placeholders in document
- Display detected placeholders
- Input fields for each placeholder
- Auto-populate document

### ⚙️ Settings Section
- Backend URL configuration
- Connection test button
- Persistent settings (localStorage)

## API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/health` | Test backend connection |
| `/ingest-document` | Upload document to RAG |
| `/generate-content` | Generate AI content |
| `/find-placeholders` | Find placeholders in template |
| `/populate-template` | Fill template with data |

## Troubleshooting

### "Backend Connection Failed"
- Ensure FastAPI server is running: `python -m uvicorn backend.main:app --reload`
- Check backend URL in plugin settings
- Server should be at `http://localhost:8000`

### "Plugin Not Loading"
- Verify manifest.xml path is correct
- Check that plugin files are being served over HTTP/HTTPS
- Ensure Office has permission to load add-in

### "Placeholders Not Found"
- Ensure placeholders follow format: `{{PLACEHOLDER_NAME}}`
- Check placeholder names don't contain spaces
- Verify template file path is correct

### "CORS Error"
- Backend already has CORS enabled for all origins
- If still error, check browser console for details
- Restart both backend and plugin

## Deployment to Office Add-in Store

1. **Create Azure App Registration**
   - Register app at https://portal.azure.com
   - Get client ID

2. **Update manifest.xml**
   - Add app registration details
   - Update source location to production URL

3. **Host Files on HTTPS Server**
   ```bash
   # Example: Azure Static Web Apps, AWS S3, or similar
   # All files must be served over HTTPS
   ```

4. **Submit to Microsoft AppSource**
   - Go to https://appsource.microsoft.com/en-us/partners/
   - Complete submission process
   - Microsoft validates and publishes

## Development Tips

### Hot Reload
While developing:
1. Keep FastAPI server running with `--reload`
2. Keep HTTP server running in word-plugin folder
3. Edit files and refresh Word (F5 or Ctrl+R)

### Testing Tips
- Use browser DevTools to debug (F12)
- Check browser console for errors
- Use Swagger UI at `http://localhost:8000/docs` to test endpoints independently
- Test each tab independently first, then full workflow

### Adding New Features
1. Add API endpoint to FastAPI backend
2. Add UI element to taskpane.html
3. Add styling to taskpane.css
4. Add function to taskpane.js
5. Test in Word plugin

## Environment Variables

The plugin respects these settings in localStorage:
```javascript
backendUrl  // Default: http://localhost:8000
```

Change programmatically:
```javascript
localStorage.setItem('backendUrl', 'https://your-server.com:8000');
```

## Security Considerations

⚠️ **Development Only Settings**:
- CORS is open to all origins (change for production)
- Backend URL can be modified in settings
- No authentication/authorization implemented (add for production)

**For Production:**
1. Implement OAuth/SSO
2. Restrict CORS to known domains
3. Use HTTPS everywhere
4. Add rate limiting
5. Validate all inputs
6. Store sensitive config securely

## Browser Compatibility

Works with:
- ✅ Chrome/Edge (latest)
- ✅ Safari (latest)
- ✅ Firefox (latest)
- ✅ Word Online
- ✅ Word Desktop (Windows & Mac)

## Next Steps

1. ✅ Backend setup complete
2. ✅ Word plugin created
3. ✅ Templates ready
4. 📝 Next: Generate templates and test
5. 🚀 Finally: Deploy to production

## Additional Resources

- [Office Add-in Documentation](https://docs.microsoft.com/en-us/office/dev/add-ins/)
- [Word API Documentation](https://docs.microsoft.com/en-us/javascript/api/word/)
- [Office Add-in Sample Gallery](https://github.com/OfficeDev/Office-Add-in-samples)

## Support

For issues or questions:
1. Check browser console (F12)
2. Review API responses in Swagger UI
3. Check backend logs for errors
4. Verify all configuration is correct
