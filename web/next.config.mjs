/** @type {import('next').NextConfig} */
// Static export: the whole website is plain HTML/JS, served by a Render Static Site (or Vercel).
const nextConfig = { reactStrictMode: true, output: "export", trailingSlash: true, images: { unoptimized: true } };
export default nextConfig;
