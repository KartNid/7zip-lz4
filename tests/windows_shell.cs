using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using ComData = System.Runtime.InteropServices.ComTypes.IDataObject;

[ComImport, Guid("000214e8-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellExtInit {
    [PreserveSig] int Initialize(IntPtr folder, [MarshalAs(UnmanagedType.Interface)] ComData data, IntPtr key);
}
[ComImport, Guid("000214e4-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IContextMenu {
    [PreserveSig] int QueryContextMenu(IntPtr menu, uint index, uint first, uint last, uint flags);
    [PreserveSig] int InvokeCommand(ref InvokeInfo info);
    [PreserveSig] int GetCommandString(UIntPtr offset, uint type, IntPtr reserved, [Out, MarshalAs(UnmanagedType.LPStr)] StringBuilder text, uint size);
}
[StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
struct InvokeInfo {
    public int size;
    public uint mask;
    public IntPtr window, verb;
    [MarshalAs(UnmanagedType.LPStr)] public string parameters;
    [MarshalAs(UnmanagedType.LPStr)] public string directory;
    public int show;
    public uint hotkey;
    public IntPtr icon;
}
public static class ShellSmoke {
    delegate bool EnumWindowProc(IntPtr window, IntPtr param);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowProc callback, IntPtr param);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] static extern IntPtr GetDlgItem(IntPtr window, int id);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr window, uint msg, IntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr SendMessage(IntPtr window, uint msg, IntPtr wparam, StringBuilder text);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint msg, IntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll")] static extern IntPtr CreatePopupMenu();
    [DllImport("user32.dll")] static extern bool DestroyMenu(IntPtr menu);
    [DllImport("user32.dll")] static extern IntPtr GetMenu(IntPtr window);
    [DllImport("user32.dll")] static extern int GetMenuItemCount(IntPtr menu);
    [DllImport("user32.dll")] static extern IntPtr GetSubMenu(IntPtr menu, int index);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetMenuString(IntPtr menu, uint id, StringBuilder text, int count, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32.dll")] static extern bool FreeLibrary(IntPtr module);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int LoadString(IntPtr module, uint id, StringBuilder text, int count);

    public static IntPtr ConflictDialog(int processId) {
        IntPtr result = IntPtr.Zero;
        EnumWindows(delegate(IntPtr window, IntPtr param) {
            uint pid;
            GetWindowThreadProcessId(window, out pid);
            if (pid == (uint)processId && GetDlgItem(window, 3525) != IntPtr.Zero) {
                result = window;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return result;
    }
    public static string DialogText(IntPtr dialog, int id) {
        var text = new StringBuilder(4096);
        IntPtr control = id == 0 ? dialog : GetDlgItem(dialog, id);
        SendMessage(control, 0x000d, new IntPtr(text.Capacity), text);
        return text.ToString();
    }
    public static bool Checked(IntPtr dialog, int id) {
        return SendMessage(GetDlgItem(dialog, id), 0x00f0, IntPtr.Zero, IntPtr.Zero) == new IntPtr(1);
    }
    public static void DecideConflict(IntPtr dialog, int action, bool all) {
        if (action != 2) {
            SendMessage(GetDlgItem(dialog, action), 0x00f5, IntPtr.Zero, IntPtr.Zero);
            SendMessage(GetDlgItem(dialog, 3528), 0x00f1, new IntPtr(all ? 1 : 0), IntPtr.Zero);
        }
        int button = action == 2 ? 2 : 1;
        if (!PostMessage(dialog, 0x0111, new IntPtr(button), GetDlgItem(dialog, button)))
            throw new Exception("Cannot confirm conflict dialog");
    }

    public static string Resource(string path) {
        IntPtr module = LoadLibraryEx(path, IntPtr.Zero, 2);
        if (module == IntPtr.Zero) throw new Exception("Cannot load resource module: " + path);
        try {
            var text = new StringBuilder(4096);
            if (LoadString(module, 100, text, text.Capacity) == 0) throw new Exception("Missing association string table");
            return text.ToString();
        } finally { FreeLibrary(module); }
    }
    public static string MenuText(IntPtr window) {
        IntPtr menu = GetMenu(window);
        var result = new StringBuilder();
        for (uint i = 0; i < GetMenuItemCount(menu); ++i) {
            var text = new StringBuilder(1024);
            GetMenuString(menu, i, text, text.Capacity, 0x400);
            result.Append(text).Append("|");
        }
        return result.ToString();
    }
    public static void Invoke(string file, string wantedVerb) {
        object extension = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("23170F69-40C1-278A-1000-000100020000")));
        IntPtr menu = CreatePopupMenu();
        try {
            var data = new DataObject(DataFormats.FileDrop, new string[] { file });
            Marshal.ThrowExceptionForHR(((IShellExtInit)extension).Initialize(IntPtr.Zero, (ComData)data, IntPtr.Zero));
            var context = (IContextMenu)extension;
            int hr = context.QueryContextMenu(menu, 0, 1, 0x7fff, 0);
            Marshal.ThrowExceptionForHR(hr);
            for (uint offset = 0; offset < (hr & 0xffff); ++offset) {
                var verb = new StringBuilder(256);
                if (context.GetCommandString(new UIntPtr(offset), 0, IntPtr.Zero, verb, 256) < 0) continue;
                if (verb.ToString() != wantedVerb) continue;
                var invoke = new InvokeInfo();
                invoke.size = Marshal.SizeOf(typeof(InvokeInfo));
                invoke.verb = new IntPtr(offset);
                invoke.directory = System.IO.Path.GetDirectoryName(file);
                invoke.show = 1;
                Marshal.ThrowExceptionForHR(context.InvokeCommand(ref invoke));
                return;
            }
            throw new Exception("Context-menu command missing: " + wantedVerb);
        } finally {
            DestroyMenu(menu);
            Marshal.FinalReleaseComObject(extension);
        }
    }
    static string ReadMenu(IntPtr menu) {
        var text = new StringBuilder();
        for (int i = 0; i < GetMenuItemCount(menu); ++i) {
            var item = new StringBuilder(1024);
            GetMenuString(menu, (uint)i, item, item.Capacity, 0x400);
            text.Append(item).Append("|");
            IntPtr child = GetSubMenu(menu, i);
            if (child != IntPtr.Zero) text.Append(ReadMenu(child));
        }
        return text.ToString();
    }
    public static string Inspect(string file) {
        object extension = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("23170F69-40C1-278A-1000-000100020000")));
        IntPtr menu = CreatePopupMenu();
        try {
            var data = new DataObject(DataFormats.FileDrop, new string[] { file });
            Marshal.ThrowExceptionForHR(((IShellExtInit)extension).Initialize(IntPtr.Zero, (ComData)data, IntPtr.Zero));
            var context = (IContextMenu)extension;
            int hr = context.QueryContextMenu(menu, 0, 1, 0x7fff, 0);
            Marshal.ThrowExceptionForHR(hr);
            var verbs = new StringBuilder(ReadMenu(menu));
            for (uint offset = 0; offset < (hr & 0xffff); ++offset) {
                var verb = new StringBuilder(256);
                if (context.GetCommandString(new UIntPtr(offset), 0, IntPtr.Zero, verb, 256) >= 0)
                    verbs.Append(verb).Append("|");
            }
            return verbs.ToString();
        } finally { DestroyMenu(menu); Marshal.FinalReleaseComObject(extension); }
    }
}
