# Deployment Guide

## Quick Start

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your API endpoint
   ```

3. **Development:**
   ```bash
   npm run dev
   ```
   Visit http://localhost:3000

4. **Production build:**
   ```bash
   npm run build
   ```

## Backend Integration

Ensure the backend API is running at `http://localhost:8000/api/v2/`

The frontend expects these API endpoints:

- `GET /system/status` - System status
- `GET /revenue/metrics` - Revenue metrics
- `GET /revenue/history?days=30` - Revenue history
- `GET /opportunities` - List opportunities
- `POST /opportunities/scan` - Scan for opportunities
- `PATCH /opportunities/:id` - Update opportunity
- `GET /products` - List products
- `POST /products/:id/deploy` - Deploy product
- `GET /settings` - Get settings
- `PATCH /settings` - Update settings

## Docker Deployment

Create a `Dockerfile`:

```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

Create `nginx.conf`:

```nginx
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Build and run:

```bash
docker build -t jarvismax-frontend .
docker run -p 3000:80 jarvismax-frontend
```

## Vercel Deployment

1. Install Vercel CLI:
   ```bash
   npm i -g vercel
   ```

2. Deploy:
   ```bash
   vercel
   ```

3. Configure environment variables in Vercel dashboard

## Netlify Deployment

1. Build command: `npm run build`
2. Publish directory: `dist`
3. Add environment variables in Netlify dashboard

## Environment Variables

- `VITE_API_BASE_URL` - Backend API URL (default: http://localhost:8000/api/v2)

## Production Checklist

- [ ] Update API endpoint in `.env`
- [ ] Enable HTTPS
- [ ] Configure CORS on backend
- [ ] Set up error tracking (Sentry, etc.)
- [ ] Configure CDN for static assets
- [ ] Enable gzip compression
- [ ] Set up monitoring and analytics
- [ ] Test all API endpoints
- [ ] Verify dark mode works correctly
- [ ] Test responsive design on mobile devices

## Performance Optimization

The build is already optimized with:

- Code splitting
- Tree shaking
- Minification
- Asset optimization
- Lazy loading for routes

Additional optimizations:

1. **Enable caching:**
   ```nginx
   location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
       expires 1y;
       add_header Cache-Control "public, immutable";
   }
   ```

2. **Gzip compression:**
   ```nginx
   gzip on;
   gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
   ```

3. **CDN:** Use a CDN like Cloudflare for static assets

## Monitoring

Recommended tools:

- **Sentry** - Error tracking
- **Google Analytics** - User analytics
- **Lighthouse** - Performance monitoring
- **LogRocket** - Session replay

## Troubleshooting

**Issue: API calls fail**
- Check CORS configuration on backend
- Verify API endpoint in `.env`
- Check network tab in browser DevTools

**Issue: Dark mode not working**
- Clear browser cache
- Check localStorage for theme preference

**Issue: Charts not rendering**
- Ensure Recharts is installed
- Check console for errors
- Verify data format matches expected types

## Support

For issues or questions, check:
- GitHub Issues
- Documentation
- API documentation at http://localhost:8000/docs
