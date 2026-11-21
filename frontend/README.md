# ShelfLife web app

The Next.js front end for ShelfLife. See the [main README](../README.md) for setup, and for how the app fits with the backend, Bifrost and Tavily.

```bash
npm install
npm run dev      # http://localhost:3000
npm run lint
npm test
npm run build
```

The app expects the API at `http://localhost:8000`. To use another address, set `NEXT_PUBLIC_API_URL` in `.env.local`.
