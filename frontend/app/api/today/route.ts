import { NextResponse } from 'next/server';

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8401';

export async function GET() {
  try {
    const res = await fetch(`${BACKEND}/today`, { cache: 'no-store' });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'backend unreachable' }, { status: 502 });
  }
}
