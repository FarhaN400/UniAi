# 🎓 UniAI — Frontend Web Application

> **Modern, responsive, university-focused AI workspace for students and faculty of Maulana Abul Kalam Azad University of Technology (MAKAUT).**  
> Built with **React 18**, **Vite**, **Tailwind CSS**, and **Lucide Icons**.

---

## 🌟 Features & Highlights

### 🔗 1. Interactive Link & Document Clickability
- **Auto-Detection of URLs**: Every raw URL (e.g. `https://makautwb.ac.in/...`, `http://...`, `www....`) in assistant answers is automatically parsed into interactive, accessible, and secured `<a>` links (`target="_blank" rel="noopener noreferrer"`).
- **Markdown Link Rendering**: Fully supports Markdown link syntax `[Notice Title](url)`.
- **Automatic PDF Badging**: Distinguishes between `.pdf` notice downloads and official web portals with dedicated icons and styling.
- **Direct Links & Documents Tray**: When assistant responses reference official notices, a dedicated **"Direct Links & Notice Documents"** chip tray appears beneath the message for one-tap access.
- **XSS & Protocol Protection**: Enforces safe protocol normalization (guards against unsafe `javascript:` or malformed URLs) and strips trailing sentence punctuation.

### 💬 2. Real-Time Conversational Chat Interface
- **Formatted Markdown Engine**: Custom high-performance renderer for bullet lists, numbered lists, blockquotes, bold text, and inline code.
- **Progress Tracking**: Real-time timer and multi-stage status indicator showing query execution phases (*"Understanding query & searching notices…"*, *"Analyzing documents…"*, *"Synthesizing claims with citations…"*) so users know local LLM inference is active.
- **One-Click Response Copying**: Quickly copy formatted answers to clipboard.
- **Graceful Error Handling & Retry**: Displays informative messages on network issues or local model timeouts with an instant **"Retry last query"** button.
- **180-Second Timeout**: Extended client-side timeout specifically optimized for local LLM inference on consumer hardware.

### 📚 3. Official Notice Sources Panel
- Slide-over drawer detailing all supporting documents cited by the RAG backend.
- Cards display notice title, issue date, and direct external link to the official PDF.
- Badge counters reflect the exact count of verified sources grounding the current response.

### 🏛️ 4. Official University Portals & Navigation
- **Quick Links in Settings**: Dedicated directory linking to MAKAUT Official Website, Examination Portal (`makautexam.net`), University Notice Board, and Student Portal (`ucanapply.com`).
- **Sidebar Integration**: Clickable portal card linking directly to official MAKAUT domains.

### 🌓 5. Design, Theming & Storage
- Seamless Light / Dark theme support with automatic persistence.
- Local conversation history saved in `localStorage` with multi-session switching and conversation deletion.
- Fully responsive design optimized for mobile, tablet, and desktop screens.
- Fallback **Demo Mode** with interactive sample responses if the FastAPI backend is not yet started.

---

## 📁 Frontend Directory Structure

```text
frontend/
├── dist/                      # Production build output
├── node_modules/              # Dependencies
├── public/                    # Static assets
├── src/
│   ├── components/
│   │   ├── Composer.jsx       # Chat input textarea with keyboard shortcuts & send button
│   │   ├── FormattedMessage.jsx # Markdown parser, URL linkifier & document detector
│   │   ├── Sidebar.jsx        # Navigation bar, conversation drawer & portal links
│   │   └── SourcePanel.jsx    # Right-hand verified sources drawer with PDF badges
│   ├── lib/
│   │   ├── api.js             # FastAPI fetch client (180s timeout, URL normalization)
│   │   └── storage.js         # LocalStorage chat history & theme persistence helpers
│   ├── pages/
│   │   ├── Chat.jsx           # Main chat stream, message rendering, progress tracker
│   │   ├── History.jsx        # Full conversation list management & viewer
│   │   ├── Home.jsx           # Welcome portal with prompt starter cards
│   │   └── Settings.jsx       # Theme toggle, backend connection info & university links
│   ├── App.jsx                # Core router, state orchestration & layout
│   ├── index.css              # Tailwind base, dark mode tokens & typography
│   └── main.jsx               # React DOM entry point
├── .env                       # Local environment configuration
├── .env.example               # Example environment variables
├── index.html                 # HTML template with DM Sans typography
├── package.json               # Node.js dependencies and build scripts
├── postcss.config.js          # PostCSS configuration
├── tailwind.config.js         # Tailwind theme customizations
└── vite.config.js             # Vite configuration
```

---

## 🚀 Getting Started

### 1. Prerequisites
- **Node.js** v18+ 
- **npm** v9+

### 2. Installation
Navigate to the `frontend` folder and install dependencies:

```bash
cd frontend
npm install
```

### 3. Configure Environment Variables
Create or edit your `.env` file in the `frontend` directory:

```bash
cp .env.example .env
```

Set the backend API URL:

```env
VITE_API_BASE_URL=http://localhost:8000
```

> **Note:** If `VITE_API_BASE_URL` is omitted, the frontend automatically runs in **Demo Mode**, allowing you to explore the UI with mocked interactions.

### 4. Run Development Server

```bash
npm run dev
```

Vite will start the application locally:
- **Local URL:** `http://localhost:5173`
- **Network URL:** `http://<your-lan-ip>:5173` (accessible on mobile/tablets on the same Wi-Fi)

---

## 🛠️ API Communication & Contracts

The frontend sends JSON requests to the FastAPI backend:

### Endpoint: `POST /api/chat`

**Request Payload:**
```json
{
  "question": "What is the WBJEE 2026 reporting deadline?",
  "conversation_id": "conv-1718000000-xyz"
}
```

**Expected Response Payload:**
```json
{
  "answer": "Document verification for WBJEE 2026 reporting takes place between 9-11 September 2025. Official source: https://makautwb.ac.in/datas/users/0-wbjee.pdf",
  "sources": [
    {
      "title": "Document verification for WBJEEB-2025 allotted students",
      "url": "https://makautwb.ac.in/datas/users/0-wbjee.pdf",
      "date": "08-09-2025"
    }
  ]
}
```

---

## 📦 Production Build

To compile and minify for production:

```bash
npm run build
```

Preview the production build locally:

```bash
npm run preview
```

---

## 🛡️ Security & Reliability Best Practices
- **No Client Secrets**: API keys (MongoDB, Pinecone, LLM endpoints) are strictly confined to the backend.
- **Rel Noopener**: All external links generated by `FormattedMessage` and `SourcePanel` include `rel="noopener noreferrer"`.
- **Input Sanitization**: Links starting with `javascript:` or `data:` schemes are blocked.
- **Network Resilience**: 180s timeout ensures slow local LLM inferences are not prematurely cut off.
