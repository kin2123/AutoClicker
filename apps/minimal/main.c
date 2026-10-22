// AutoClicker Minimal - 极简连点器
// 单窗口三件套：间隔 / 启停 / 状态。F6 全局热键，托盘常驻，零外部依赖。
#define _WIN32_WINNT 0x0601
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdlib.h>

#define APP_TITLE   L"连点器"
#define WM_TRAY     (WM_APP + 1)
#define WM_RUNSTATE (WM_APP + 2)

#define ID_EDIT  1001
#define ID_BTN   1002
#define ID_BG    0x00FFFFFF
#define ID_DOT   0x003A3A3A

#define IDM_SHOW 2001
#define IDM_TOGGLE 2002
#define IDM_EXIT 2003

static HWND     g_hwnd, g_hEdit, g_hBtn;
static HFONT    g_fLabel, g_fEdit, g_fBtn, g_fDot;
static int      g_running = 0;
static int      g_interval = 100;
static float    g_scale = 1.0f;
static int      g_exit = 0;
static NOTIFYICONDATAW g_nid;
static WCHAR    g_iniPath[MAX_PATH];
static HBRUSH   g_bgBrush;
static HANDLE   g_thread = NULL;
static volatile LONG g_stopFlag = 0;

static int S(int v) { return (int)(v * g_scale + 0.5f); }

static int g_hover = 0;
static WNDPROC g_oldBtnProc;

static LRESULT CALLBACK BtnProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_MOUSEMOVE:
        if (!g_hover) {
            g_hover = 1;
            InvalidateRect(h, NULL, TRUE);
            TRACKMOUSEEVENT t = {sizeof(t), TME_LEAVE, h, 0};
            TrackMouseEvent(&t);
        }
        break;
    case WM_MOUSELEAVE:
        g_hover = 0;
        InvalidateRect(h, NULL, TRUE);
        break;
    }
    return CallWindowProcW(g_oldBtnProc, h, m, w, l);
}

static void shade(COLORREF c, int delta, COLORREF *out) {
    int r = GetRValue(c) + delta, g = GetGValue(c) + delta, b = GetBValue(c) + delta;
    if (r < 0) r = 0; if (r > 255) r = 255;
    if (g < 0) g = 0; if (g > 255) g = 255;
    if (b < 0) b = 0; if (b > 255) b = 255;
    *out = RGB(r, g, b);
}

static void paint_button_item(LPDRAWITEMSTRUCT d) {
    RECT r = d->rcItem;
    HBRUSH pageBrush = CreateSolidBrush(RGB(0xFF, 0xFF, 0xFF));
    FillRect(d->hDC, &r, pageBrush);
    DeleteObject(pageBrush);

    COLORREF base = g_running ? RGB(0xC5, 0x3B, 0x2E) : RGB(0x22, 0x26, 0x2B);
    if (d->itemState & ODS_SELECTED) shade(base, -22, &base);
    else if (g_hover)                shade(base, 16, &base);

    HBRUSH b = CreateSolidBrush(base);
    HPEN   p = CreatePen(PS_SOLID, 1, base);
    HGDIOBJ ob = SelectObject(d->hDC, b);
    HGDIOBJ op = SelectObject(d->hDC, p);
    int rad = S(10);
    RoundRect(d->hDC, r.left, r.top, r.right, r.bottom, rad, rad);
    SelectObject(d->hDC, ob);
    SelectObject(d->hDC, op);
    DeleteObject(b);
    DeleteObject(p);

    SetBkMode(d->hDC, TRANSPARENT);
    SetTextColor(d->hDC, RGB(0xFF, 0xFF, 0xFF));
    SelectObject(d->hDC, g_fBtn);
    WCHAR txt[32];
    GetWindowTextW(d->hwndItem, txt, 32);
    DrawTextW(d->hDC, txt, -1, &r, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
}

static WCHAR *exe_dir_path(const WCHAR *name, WCHAR *out) {
    WCHAR dir[MAX_PATH];
    GetModuleFileNameW(NULL, dir, MAX_PATH);
    WCHAR *p = wcsrchr(dir, L'\\');
    if (p) *(p + 1) = L'\0';
    _snwprintf(out, MAX_PATH, L"%s%s", dir, name);
    return out;
}

static void load_cfg(void) {
    g_interval = (int)GetPrivateProfileIntW(L"cfg", L"interval", 100, g_iniPath);
    if (g_interval < 1)    g_interval = 1;
    if (g_interval > 60000) g_interval = 60000;
}

static void save_cfg(void) {
    WCHAR buf[32];
    _snwprintf(buf, 32, L"%d", g_interval);
    WritePrivateProfileStringW(L"cfg", L"interval", buf, g_iniPath);
}

static void do_click(void) {
    INPUT in[2];
    ZeroMemory(in, sizeof(in));
    in[0].type = INPUT_MOUSE;
    in[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    in[1].type = INPUT_MOUSE;
    in[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;
    SendInput(2, in, sizeof(INPUT));
}

static DWORD WINAPI clicker_thread(LPVOID arg) {
    LARGE_INTEGER freq, next, now;
    (void)arg;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&next);
    while (!g_stopFlag) {
        LONG iv = (LONG)InterlockedCompareExchange((LONG *)&g_interval, 0, 0);
        LONGLONG step = (LONGLONG)((double)iv / 1000.0 * freq.QuadPart);
        if (step < 1) step = 1;
        next.QuadPart += step;
        do_click();
        for (;;) {
            QueryPerformanceCounter(&now);
            LONGLONG remain = next.QuadPart - now.QuadPart;
            if (remain <= 0) break;
            double ms = (double)remain * 1000.0 / (double)freq.QuadPart;
            if (ms > 2.0) Sleep((DWORD)(ms - 1.5));
            else Sleep(0);
        }
    }
    return 0;
}

static void set_running(int on) {
    if (on == g_running) return;
    g_running = on;
    if (on) {
        g_stopFlag = 0;
        timeBeginPeriod(1);
        g_thread = CreateThread(NULL, 0, clicker_thread, NULL, 0, NULL);
        SetWindowTextW(g_hBtn, L"停止  (F6)");
        InvalidateRect(g_hBtn, NULL, TRUE);
        g_nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        lstrcpyW(g_nid.szTip, L"连点器 — 运行中");
        Shell_NotifyIconW(NIM_MODIFY, &g_nid);
    } else {
        g_stopFlag = 1;
        if (g_thread) { WaitForSingleObject(g_thread, 3000); CloseHandle(g_thread); g_thread = NULL; }
        timeEndPeriod(1);
        SetWindowTextW(g_hBtn, L"开始  (F6)");
        InvalidateRect(g_hBtn, NULL, TRUE);
        lstrcpyW(g_nid.szTip, L"连点器 — 已停止");
        Shell_NotifyIconW(NIM_MODIFY, &g_nid);
        save_cfg();
    }
    InvalidateRect(g_hwnd, NULL, TRUE);
}

static void read_interval_from_ui(void) {
    WCHAR buf[32] = {0};
    GetWindowTextW(g_hEdit, buf, 32);
    int v = _wtoi(buf);
    if (v < 1) v = 1;
    if (v > 60000) v = 60000;
    g_interval = v;
    _snwprintf(buf, 32, L"%d", v);
    if (wcscmp(buf, L"") != 0) {
        WCHAR cur[32] = {0};
        GetWindowTextW(g_hEdit, cur, 32);
        if (wcscmp(cur, buf) != 0) SetWindowTextW(g_hEdit, buf);
    }
}

static void paint_main(HWND h) {
    PAINTSTRUCT ps;
    HDC dc = BeginPaint(h, &ps);
    RECT rc;
    GetClientRect(h, &rc);
    int w = rc.right, ht = rc.bottom;

    HDC mem = CreateCompatibleDC(dc);
    HBITMAP bmp = CreateCompatibleBitmap(dc, w, ht);
    HGDIOBJ old = SelectObject(mem, bmp);

    RECT full = {0, 0, w, ht};
    FillRect(mem, &full, g_bgBrush);

    SetBkMode(mem, TRANSPARENT);
    SelectObject(mem, g_fLabel);
    SetTextColor(mem, RGB(0x8A, 0x8A, 0x8A));
    RECT lbl = {S(24), S(18), w - S(24), S(38)};
    DrawTextW(mem, L"点击间隔（毫秒）", -1, &lbl, DT_LEFT | DT_SINGLELINE);

    HPEN pen = CreatePen(PS_SOLID, 1, RGB(0xE8, 0xE8, 0xE8));
    HGDIOBJ oldPen = SelectObject(mem, pen);
    MoveToEx(mem, S(24), S(194), NULL);
    LineTo(mem, w - S(24), S(194));
    SelectObject(mem, oldPen);
    DeleteObject(pen);

    int cy = S(222);
    SelectObject(mem, g_fDot);
    SetTextColor(mem, g_running ? RGB(0x2E, 0xA0, 0x6A) : RGB(0xC4, 0xC4, 0xC4));
    RECT dotRc = {S(22), cy - S(12), S(38), cy + S(12)};
    DrawTextW(mem, L"\u25CF", -1, &dotRc, DT_LEFT | DT_SINGLELINE | DT_VCENTER);

    SelectObject(mem, g_fLabel);
    SetTextColor(mem, g_running ? RGB(0x2E, 0xA0, 0x6A) : RGB(0x8A, 0x8A, 0x8A));
    RECT st = {S(40), cy - S(10), w - S(24), cy + S(10)};
    DrawTextW(mem, g_running ? L"运行中" : L"已停止", -1, &st, DT_LEFT | DT_SINGLELINE | DT_VCENTER);

    SetTextColor(mem, RGB(0xB0, 0xB0, 0xB0));
    RECT hint = {S(24), S(252), w - S(24), S(272)};
    DrawTextW(mem, L"F6 启停 · 关闭窗口最小化到托盘", -1, &hint, DT_LEFT | DT_SINGLELINE);

    BitBlt(dc, 0, 0, w, ht, mem, 0, 0, SRCCOPY);
    SelectObject(mem, old);
    DeleteObject(bmp);
    DeleteDC(mem);
    EndPaint(h, &ps);
}

static void toggle(void) {
    read_interval_from_ui();
    set_running(!g_running);
}

static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
    case WM_CREATE: {
        g_scale = (float)GetDeviceCaps(GetDC(h), LOGPIXELSX) / 96.0f;
        ReleaseDC(h, GetDC(h));
        if (g_scale < 1.0f) g_scale = 1.0f;
        g_scale = 1.0f;

        g_fLabel = CreateFontW(-S(13), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                               OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                               DEFAULT_PITCH, L"Microsoft YaHei UI");
        g_fEdit = CreateFontW(-S(34), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET,
                              OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                              DEFAULT_PITCH, L"Microsoft YaHei UI");
        g_fDot = CreateFontW(-S(15), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                             OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                             DEFAULT_PITCH, L"Microsoft YaHei UI");
        g_fBtn = CreateFontW(-S(17), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                             OUT_TT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                             DEFAULT_PITCH, L"Microsoft YaHei UI");

        g_hEdit = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_NUMBER | ES_CENTER,
                                  S(24), S(44), S(252), S(58), h, (HMENU)ID_EDIT, NULL, NULL);
        SendMessageW(g_hEdit, WM_SETFONT, (WPARAM)g_fEdit, TRUE);

        g_hBtn = CreateWindowExW(0, L"BUTTON", L"开始  (F6)",
                                 WS_CHILD | WS_VISIBLE | BS_OWNERDRAW,
                                 S(24), S(126), S(252), S(56), h, (HMENU)ID_BTN, NULL, NULL);
        SendMessageW(g_hBtn, WM_SETFONT, (WPARAM)g_fBtn, TRUE);
        g_oldBtnProc = (WNDPROC)SetWindowLongPtrW(g_hBtn, GWLP_WNDPROC, (LONG_PTR)BtnProc);

        WCHAR buf[32];
        _snwprintf(buf, 32, L"%d", g_interval);
        SetWindowTextW(g_hEdit, buf);

        g_nid.cbSize = sizeof(g_nid);
        g_nid.hWnd = h;
        g_nid.uID = 1;
        g_nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
        g_nid.uCallbackMessage = WM_TRAY;
        g_nid.hIcon = LoadIconW(GetModuleHandleW(NULL), L"APPICON");
        lstrcpyW(g_nid.szTip, L"连点器 — 已停止");
        Shell_NotifyIconW(NIM_ADD, &g_nid);

        RegisterHotKey(h, 1, 0, VK_F6);
        return 0;
    }
    case WM_PAINT: paint_main(h); return 0;
    case WM_DRAWITEM:
        if (((LPDRAWITEMSTRUCT)l)->CtlID == ID_BTN) paint_button_item((LPDRAWITEMSTRUCT)l);
        return TRUE;
    case WM_ERASEBKGND: return 1;
    case WM_CTLCOLOREDIT: {
        SetBkColor((HDC)w, RGB(0xF6, 0xF6, 0xF6));
        SetTextColor((HDC)w, RGB(0x1A, 0x1A, 0x1A));
        return (LRESULT)GetStockObject(NULL_BRUSH);
    }
    case WM_CTLCOLORBTN: {
        SetBkColor((HDC)w, RGB(0x2E, 0xA0, 0x6A));
        return (LRESULT)g_bgBrush;
    }
    case WM_HOTKEY:
        if (w == 1) toggle();
        return 0;
    case WM_COMMAND:
        if (LOWORD(w) == ID_BTN && HIWORD(w) == BN_CLICKED) toggle();
        return 0;
    case WM_TRAY:
        if (l == WM_LBUTTONDBLCLK) {
            ShowWindow(h, SW_SHOW); SetForegroundWindow(h);
        } else if (l == WM_RBUTTONUP) {
            HMENU pm = CreatePopupMenu();
            AppendMenuW(pm, MF_STRING, IDM_SHOW, L"显示窗口");
            AppendMenuW(pm, MF_STRING, IDM_TOGGLE, g_running ? L"停止" : L"开始");
            AppendMenuW(pm, MF_SEPARATOR, 0, NULL);
            AppendMenuW(pm, MF_STRING, IDM_EXIT, L"退出");
            POINT pt; GetCursorPos(&pt);
            SetForegroundWindow(h);
            int cmd = (int)TrackPopupMenu(pm, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, h, NULL);
            DestroyMenu(pm);
            if (cmd == IDM_SHOW) { ShowWindow(h, SW_SHOW); SetForegroundWindow(h); }
            else if (cmd == IDM_TOGGLE) toggle();
            else if (cmd == IDM_EXIT) { g_exit = 1; DestroyWindow(h); }
        }
        return 0;
    case WM_CLOSE:
        ShowWindow(h, SW_HIDE);
        if (g_running) set_running(0);
        return 0;
    case WM_DESTROY:
        set_running(0);
        UnregisterHotKey(h, 1);
        Shell_NotifyIconW(NIM_DELETE, &g_nid);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

static void enable_dpi(void) {
    HMODULE u = LoadLibraryW(L"user32.dll");
    if (u) {
        typedef BOOL (WINAPI *PSetCtx)(HANDLE);
        PSetCtx f = (PSetCtx)GetProcAddress(u, "SetProcessDpiAwarenessContext");
        if (f) {
            f((HANDLE)-4); // PER_MONITOR_AWARE_V2
            return;
        }
    }
    SetProcessDPIAware();
}

int WINAPI wWinMain(HINSTANCE hi, HINSTANCE hp, LPWSTR cmd, int show) {
    (void)hp; (void)cmd;
    enable_dpi();

    HANDLE mutex = CreateMutexW(NULL, TRUE, L"AutoClickerMinimal_SingleInstance");
    if (mutex && GetLastError() == ERROR_ALREADY_EXISTS) {
        HWND ex = FindWindowW(L"AutoClickerMinimal", NULL);
        if (ex) { ShowWindow(ex, SW_SHOW); SetForegroundWindow(ex); }
        return 0;
    }

    exe_dir_path(L"AutoClicker-Minimal.ini", g_iniPath);
    load_cfg();

    g_bgBrush = CreateSolidBrush(RGB(0xFF, 0xFF, 0xFF));

    WNDCLASSEXW wc = {0};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = WndProc;
    wc.hInstance = hi;
    wc.hIcon = LoadIconW(hi, L"APPICON");
    wc.hIconSm = LoadIconW(hi, L"APPICON");
    wc.hCursor = LoadCursorW(NULL, IDC_ARROW);
    wc.hbrBackground = g_bgBrush;
    wc.lpszClassName = L"AutoClickerMinimal";
    RegisterClassExW(&wc);

    DWORD style = WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
    DWORD exStyle = WS_EX_APPWINDOW;
    RECT rc = {0, 0, 300, 286};
    AdjustWindowRectEx(&rc, style, FALSE, exStyle);
    g_hwnd = CreateWindowExW(exStyle, L"AutoClickerMinimal", APP_TITLE,
                             style,
                             CW_USEDEFAULT, CW_USEDEFAULT,
                             rc.right - rc.left, rc.bottom - rc.top,
                             NULL, NULL, hi, NULL);
    ShowWindow(g_hwnd, show);
    UpdateWindow(g_hwnd);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        if (msg.message == WM_KEYDOWN && msg.wParam == VK_ESCAPE) continue;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    if (mutex) CloseHandle(mutex);
    return 0;
}
