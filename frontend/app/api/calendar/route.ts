import { NextResponse, NextRequest } from 'next/server';

const BACKEND = process.env.BACKEND_URL || 'http://localhost:8401';

export async function GET(request: NextRequest) {
  try {
    const year = request.nextUrl.searchParams.get('year');
    const month = request.nextUrl.searchParams.get('month');
    const uid = request.nextUrl.searchParams.get('uid') || 'default';
    const params = new URLSearchParams();
    if (year) params.set('year', year);
    if (month) params.set('month', month);
    const url = `${BACKEND}/calendar${params.toString() ? '?' + params : ''}`;
    const res = await fetch(url, { cache: 'no-store', headers: { 'X-User-Id': uid } });
    const data = await res.json();
    return NextResponse.json(data);
  } catch {
    return NextResponse.json({ days: [] }, { status: 502 });
  }
}
