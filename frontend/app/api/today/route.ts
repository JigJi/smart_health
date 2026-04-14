import { NextResponse } from 'next/server';
import { NextRequest } from 'next/server';

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8401';

export async function GET(request: NextRequest) {
  try {
    const date = request.nextUrl.searchParams.get('date');
    const uid = request.nextUrl.searchParams.get('uid') || 'default';
    const url = date ? `${BACKEND}/today?date=${date}` : `${BACKEND}/today`;
    const res = await fetch(url, { cache: 'no-store', headers: { 'X-User-Id': uid } });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ error: 'backend unreachable' }, { status: 502 });
  }
}
