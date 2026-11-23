import "./globals.css";

export const metadata = {
  title: "TechTokri · ShopBot AI storefront",
  description: "Gadgets delivered across Pakistan, with an AI sales assistant that finds products, fills your cart and books orders.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
