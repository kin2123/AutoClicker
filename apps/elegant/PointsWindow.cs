using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;

namespace AutoClickerPro
{
    public class PointsWindow : Window
    {
        [DllImport("user32.dll")]
        static extern bool GetCursorPos(out NativePoint p);

        [StructLayout(LayoutKind.Sequential)]
        struct NativePoint { public int X, Y; }

        public List<int[]> Result;
        readonly ListBox _list = new ListBox();

        public PointsWindow(List<int[]> initial)
        {
            Result = new List<int[]>(initial);
            WindowStyle = WindowStyle.None;
            AllowsTransparency = true;
            Background = Brushes.Transparent;
            Width = 340;
            Height = 430;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            Topmost = true;
            ResizeMode = ResizeMode.NoResize;

            var outer = new Border
            {
                Margin = new Thickness(14),
                CornerRadius = new CornerRadius(14),
                Background = FindBrush("CardBrush"),
                Effect = new System.Windows.Media.Effects.DropShadowEffect
                { BlurRadius = 24, ShadowDepth = 0, Opacity = 0.6 }
            };
            Content = outer;

            var root = new Grid();
            root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(44) });
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            outer.Child = root;

            var title = new TextBlock
            {
                Text = "  多点循环坐标",
                Foreground = FindBrush("TextBrush"),
                FontSize = 13,
                FontWeight = FontWeights.Medium,
                VerticalAlignment = VerticalAlignment.Center
            };
            var titleBar = new Grid();
            titleBar.Children.Add(title);
            var close = new Button
            {
                Content = "✕",
                Width = 40,
                Height = 30,
                HorizontalAlignment = HorizontalAlignment.Right,
                Foreground = FindBrush("TextDimBrush"),
                Background = Brushes.Transparent
            };
            close.Click += (s, e) => Close();
            titleBar.Children.Add(close);
            titleBar.MouseLeftButtonDown += (s, e) => DragMove();
            Grid.SetRow(titleBar, 0);
            root.Children.Add(titleBar);

            var hint = new TextBlock
            {
                Text = "  点击坐标将按顺序循环执行",
                Foreground = FindBrush("TextDimBrush"),
                FontSize = 11.5,
                Margin = new Thickness(4, 0, 0, 6)
            };
            Grid.SetRow(hint, 1);
            root.Children.Add(hint);

            _list.Background = Brushes.Transparent;
            _list.BorderThickness = new Thickness(0);
            _list.Margin = new Thickness(12, 0, 12, 10);
            _list.Foreground = FindBrush("TextBrush");
            Grid.SetRow(_list, 2);
            root.Children.Add(_list);
            Reload();

            var btns = new UniformGrid { Columns = 4 };
            btns.Children.Add(MakeBtn("加当前位置", (s, e) =>
            {
                NativePoint p;
                GetCursorPos(out p);
                Result.Add(new[] { p.X, p.Y });
                Reload();
            }));
            btns.Children.Add(MakeBtn("删除选中", (s, e) =>
            {
                if (_list.SelectedIndex >= 0) { Result.RemoveAt(_list.SelectedIndex); Reload(); }
            }));
            btns.Children.Add(MakeBtn("清空", (s, e) => { Result.Clear(); Reload(); }));
            btns.Children.Add(MakeBtn("确定", (s, e) => Close()));
            var wrap = new Border { Padding = new Thickness(12), Child = btns };
            Grid.SetRow(wrap, 3);
            root.Children.Add(wrap);
        }

        Button MakeBtn(string text, RoutedEventHandler onClick)
        {
            var b = new Button
            {
                Content = text,
                FontSize = 12,
                Margin = new Thickness(3, 0, 3, 0),
                Padding = new Thickness(2, 6, 2, 6),
                Cursor = Cursors.Hand,
                Foreground = FindBrush("TextDimBrush"),
                Background = FindBrush("FieldBrush"),
                BorderThickness = new Thickness(0)
            };
            b.Click += onClick;
            return b;
        }

        void Reload()
        {
            _list.Items.Clear();
            for (int i = 0; i < Result.Count; i++)
                _list.Items.Add(string.Format("{0}.  ({1}, {2})", i + 1, Result[i][0], Result[i][1]));
        }

        static Brush FindBrush(string key)
        {
            return (Brush)Application.Current.FindResource(key);
        }
    }
}
