# JarvisMax AI OS - Frontend

A production-ready React TypeScript frontend for JarvisMax AI OS with Vite, Tailwind CSS, and premium UI/UX.

## Features

- **Dashboard**: Real-time system status, revenue metrics, opportunities, and products overview
- **Opportunities**: Scan and manage business opportunities with filterable tables
- **Products**: Deploy and manage AI-powered products
- **Revenue Analytics**: Comprehensive revenue tracking with interactive charts (Recharts)
- **Settings**: Dark mode toggle, notifications, and automation configuration

## Tech Stack

- **React 18** - Modern React with hooks
- **TypeScript** - Type-safe development
- **Vite** - Lightning-fast build tool
- **Tailwind CSS** - Utility-first styling
- **React Router** - Client-side routing
- **Axios** - HTTP client for API calls
- **Recharts** - Beautiful charts and graphs
- **Lucide React** - Premium icon library

## Getting Started

### Prerequisites

- Node.js 18+ and npm/yarn/pnpm

### Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

The app will be available at http://localhost:3000

## Project Structure

```
frontend/
├── src/
│   ├── api/              # API client and endpoints
│   │   └── client.ts     # Axios-based API client
│   ├── components/       # Reusable UI components
│   │   ├── Badge.tsx
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Layout.tsx
│   │   ├── LoadingSpinner.tsx
│   │   └── StatCard.tsx
│   ├── hooks/            # Custom React hooks
│   │   └── useTheme.ts
│   ├── pages/            # Page components
│   │   ├── Dashboard.tsx
│   │   ├── Opportunities.tsx
│   │   ├── Products.tsx
│   │   ├── Revenue.tsx
│   │   └── Settings.tsx
│   ├── types/            # TypeScript type definitions
│   │   └── index.ts
│   ├── utils/            # Utility functions
│   │   ├── cn.ts
│   │   └── format.ts
│   ├── App.tsx           # Main app component
│   ├── main.tsx          # Entry point
│   └── index.css         # Global styles
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
└── tailwind.config.js
```

## API Configuration

The frontend connects to the backend API at `http://localhost:8000/api/v2/`.

To change the API endpoint, update the `BASE_URL` in `src/api/client.ts`.

## Features Details

### Dashboard
- System status with CPU/memory monitoring
- Revenue metrics (MRR/ARR) with growth trends
- Recent opportunities and products
- Animated cards with smooth transitions

### Opportunities
- Scan button to discover new opportunities
- Filterable table by status, type, and search
- Update opportunity status inline
- Pagination support

### Products
- Grid view of all products
- Deploy products with one click
- Filter by category and status
- Real-time deployment status

### Revenue
- Interactive charts with Recharts
- MRR/ARR comparison
- Customer growth tracking
- Revenue insights and breakdown
- Multiple time range views (7D, 30D, 90D, 365D)

### Settings
- Dark/light mode toggle
- Notification preferences
- Auto-scan configuration
- System information

## Styling

The app uses Tailwind CSS with a custom color palette and dark mode support:

- Primary color: Blue (#0ea5e9)
- Smooth animations and transitions
- Responsive design for all screen sizes
- Custom scrollbars
- Hover effects and loading states

## API Client

The API client (`src/api/client.ts`) provides type-safe methods for all backend endpoints:

- `getSystemStatus()` - Get system status
- `getRevenueMetrics()` - Get revenue metrics
- `getOpportunities()` - List opportunities with filters
- `scanOpportunities()` - Start opportunity scan
- `getProducts()` - List products with filters
- `deployProduct()` - Deploy a product
- `getSettings()` - Get user settings
- `updateSettings()` - Update user settings

## Development

```bash
# Run development server with hot reload
npm run dev

# Type check
npm run tsc

# Lint code
npm run lint

# Build for production
npm run build
```

## Production Build

```bash
# Build optimized production bundle
npm run build

# Preview production build locally
npm run preview
```

The production build will be in the `dist/` directory.

## Environment Variables

Create a `.env` file for environment-specific configuration:

```env
VITE_API_BASE_URL=http://localhost:8000/api/v2
```

## Browser Support

- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)

## License

MIT
