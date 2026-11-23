"use client";
import Link from "next/link";

export default function Header({ cartCount, onCart, admin }) {
  return (
    <header className="top">
      <div className="wrap top-in">
        <Link href="/" className="logo"><span className="mark">T</span>TechTokri<span className="by">with ShopBot</span></Link>
        <nav>
          <Link href="/">Shop</Link>
          <Link href="/orders">My orders</Link>
          <Link href="/admin" className={admin ? "on" : ""}>Seller admin</Link>
          {onCart && <button className="cart-btn" onClick={onCart}>Cart <span>{cartCount || 0}</span></button>}
        </nav>
      </div>
    </header>
  );
}
