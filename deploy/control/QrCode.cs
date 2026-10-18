// A small QR code encoder, written here so nothing has to be downloaded.
// Byte mode, error correction level M, versions 1 to 10 (up to 213 bytes).
// C# 5 only, like the rest of the control app.
using System;
using System.Drawing;
using System.Text;

namespace VisionGuardControl
{
    static class QrCode
    {
        // Level M, per version 1..10: error-correction codewords per block, then
        // (blocks, data codewords per block) for group 1 and group 2.
        static readonly int[][] Table = new int[][]
        {
            new int[] { 10, 1, 16, 0, 0 },
            new int[] { 16, 1, 28, 0, 0 },
            new int[] { 26, 1, 44, 0, 0 },
            new int[] { 18, 2, 32, 0, 0 },
            new int[] { 24, 2, 43, 0, 0 },
            new int[] { 16, 4, 27, 0, 0 },
            new int[] { 18, 4, 31, 0, 0 },
            new int[] { 22, 2, 38, 2, 39 },
            new int[] { 22, 3, 36, 2, 37 },
            new int[] { 26, 4, 43, 1, 44 }
        };

        static readonly int[][] Alignment = new int[][]
        {
            new int[0],
            new int[] { 6, 18 },
            new int[] { 6, 22 },
            new int[] { 6, 26 },
            new int[] { 6, 30 },
            new int[] { 6, 34 },
            new int[] { 6, 22, 38 },
            new int[] { 6, 24, 42 },
            new int[] { 6, 26, 46 },
            new int[] { 6, 28, 50 }
        };

        // ---- public ---------------------------------------------------------

        // Returns the dark/light modules (true = dark), without the quiet zone.
        public static bool[,] Encode(string text)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(text);
            int version = 0;
            for (int v = 1; v <= 10; v++)
            {
                if (bytes.Length <= DataBytes(v)) { version = v; break; }
            }
            if (version == 0)
                throw new ArgumentException("The text is too long for a QR code here (" + bytes.Length + " bytes, at most 213).");

            byte[] data = BuildData(bytes, version);
            byte[] all = AddErrorCorrection(data, version);
            return Draw(all, version);
        }

        // Quiet zone of 4 modules, black on white.
        public static Bitmap Render(bool[,] modules, int moduleSize)
        {
            int n = modules.GetLength(0);
            int side = (n + 8) * moduleSize;
            Bitmap bmp = new Bitmap(side, side, System.Drawing.Imaging.PixelFormat.Format24bppRgb);
            using (Graphics g = Graphics.FromImage(bmp))
            {
                g.Clear(Color.White);
                for (int y = 0; y < n; y++)
                {
                    for (int x = 0; x < n; x++)
                    {
                        if (modules[y, x])
                            g.FillRectangle(Brushes.Black, (x + 4) * moduleSize, (y + 4) * moduleSize, moduleSize, moduleSize);
                    }
                }
            }
            return bmp;
        }

        public static int SideInModules(bool[,] modules)
        {
            return modules.GetLength(0) + 8;
        }

        // ---- data -----------------------------------------------------------

        static int DataCodewords(int version)
        {
            int[] t = Table[version - 1];
            return t[1] * t[2] + t[3] * t[4];
        }

        static int DataBytes(int version)
        {
            int countBits = version >= 10 ? 16 : 8;
            return (DataCodewords(version) * 8 - 4 - countBits) / 8;
        }

        static byte[] BuildData(byte[] bytes, int version)
        {
            int capacityBits = DataCodewords(version) * 8;
            BitList bits = new BitList();
            bits.Add(4, 4);                                  // byte mode
            bits.Add(bytes.Length, version >= 10 ? 16 : 8);
            for (int i = 0; i < bytes.Length; i++) bits.Add(bytes[i], 8);
            bits.Add(0, Math.Min(4, capacityBits - bits.Count));   // terminator
            while (bits.Count % 8 != 0) bits.Add(0, 1);
            int pad = 0xEC;
            while (bits.Count < capacityBits)
            {
                bits.Add(pad, 8);
                pad = pad == 0xEC ? 0x11 : 0xEC;
            }
            return bits.ToBytes();
        }

        class BitList
        {
            readonly System.Collections.Generic.List<bool> list = new System.Collections.Generic.List<bool>();
            public int Count { get { return list.Count; } }
            public void Add(int value, int length)
            {
                for (int i = length - 1; i >= 0; i--) list.Add(((value >> i) & 1) != 0);
            }
            public byte[] ToBytes()
            {
                byte[] r = new byte[list.Count / 8];
                for (int i = 0; i < list.Count; i++)
                {
                    if (list[i]) r[i >> 3] |= (byte)(0x80 >> (i & 7));
                }
                return r;
            }
        }

        // ---- Reed-Solomon over GF(256), polynomial 0x11D --------------------

        static int Multiply(int x, int y)
        {
            int z = 0;
            for (int i = 7; i >= 0; i--)
            {
                z = (z << 1) ^ ((z >> 7) * 0x11D);
                z ^= ((y >> i) & 1) * x;
            }
            return z;
        }

        // The standard generator polynomial (x - a^0)(x - a^1)... without its leading 1.
        static byte[] Divisor(int degree)
        {
            byte[] result = new byte[degree];
            result[degree - 1] = 1;
            int root = 1;
            for (int i = 0; i < degree; i++)
            {
                for (int j = 0; j < degree; j++)
                {
                    result[j] = (byte)Multiply(result[j], root);
                    if (j + 1 < degree) result[j] ^= result[j + 1];
                }
                root = Multiply(root, 2);
            }
            return result;
        }

        static byte[] Remainder(byte[] data, byte[] divisor)
        {
            byte[] result = new byte[divisor.Length];
            for (int k = 0; k < data.Length; k++)
            {
                int factor = data[k] ^ result[0];
                Array.Copy(result, 1, result, 0, result.Length - 1);
                result[result.Length - 1] = 0;
                for (int i = 0; i < result.Length; i++) result[i] ^= (byte)Multiply(divisor[i], factor);
            }
            return result;
        }

        static byte[] AddErrorCorrection(byte[] data, int version)
        {
            int[] t = Table[version - 1];
            int eccLen = t[0];
            int blocks = t[1] + t[3];
            byte[][] dataBlocks = new byte[blocks][];
            byte[][] eccBlocks = new byte[blocks][];
            byte[] divisor = Divisor(eccLen);
            int pos = 0;
            for (int b = 0; b < blocks; b++)
            {
                int len = b < t[1] ? t[2] : t[4];
                dataBlocks[b] = new byte[len];
                Array.Copy(data, pos, dataBlocks[b], 0, len);
                pos += len;
                eccBlocks[b] = Remainder(dataBlocks[b], divisor);
            }

            byte[] result = new byte[data.Length + blocks * eccLen];
            int at = 0;
            int longest = Math.Max(t[2], t[3] > 0 ? t[4] : 0);
            for (int i = 0; i < longest; i++)
            {
                for (int b = 0; b < blocks; b++)
                {
                    if (i < dataBlocks[b].Length) result[at++] = dataBlocks[b][i];
                }
            }
            for (int i = 0; i < eccLen; i++)
            {
                for (int b = 0; b < blocks; b++) result[at++] = eccBlocks[b][i];
            }
            return result;
        }

        // ---- the picture ----------------------------------------------------

        static bool Bit(int value, int i)
        {
            return ((value >> i) & 1) != 0;
        }

        static bool[,] Draw(byte[] codewords, int version)
        {
            int size = 17 + 4 * version;
            bool[,] m = new bool[size, size];      // [row, column]
            bool[,] fn = new bool[size, size];     // true = not data

            // timing
            for (int i = 0; i < size; i++)
            {
                SetFn(m, fn, 6, i, i % 2 == 0);
                SetFn(m, fn, i, 6, i % 2 == 0);
            }
            // finders with their separators
            Finder(m, fn, 3, 3);
            Finder(m, fn, size - 4, 3);
            Finder(m, fn, 3, size - 4);
            // alignment
            int[] pos = Alignment[version - 1];
            int n = pos.Length;
            for (int i = 0; i < n; i++)
            {
                for (int j = 0; j < n; j++)
                {
                    if ((i == 0 && j == 0) || (i == 0 && j == n - 1) || (i == n - 1 && j == 0)) continue;
                    for (int dy = -2; dy <= 2; dy++)
                    {
                        for (int dx = -2; dx <= 2; dx++)
                        {
                            int dist = Math.Max(Math.Abs(dx), Math.Abs(dy));
                            SetFn(m, fn, pos[i] + dx, pos[j] + dy, dist != 1);
                        }
                    }
                }
            }
            FormatBits(m, fn, size, 0);     // reserve the format areas
            if (version >= 7) VersionBits(m, fn, size, version);

            // data, zig-zag from the bottom right
            int bitIndex = 0;
            int total = codewords.Length * 8;
            for (int right = size - 1; right >= 1; right -= 2)
            {
                if (right == 6) right = 5;
                for (int vert = 0; vert < size; vert++)
                {
                    for (int j = 0; j < 2; j++)
                    {
                        int x = right - j;
                        bool upward = ((right + 1) & 2) == 0;
                        int y = upward ? size - 1 - vert : vert;
                        if (!fn[y, x] && bitIndex < total)
                        {
                            m[y, x] = Bit(codewords[bitIndex >> 3], 7 - (bitIndex & 7));
                            bitIndex++;
                        }
                    }
                }
            }

            // try every mask, keep the one with the lowest penalty
            int best = 0;
            int bestPenalty = int.MaxValue;
            for (int mask = 0; mask < 8; mask++)
            {
                ApplyMask(m, fn, size, mask);
                FormatBits(m, fn, size, mask);
                int p = Penalty(m, size);
                if (p < bestPenalty) { bestPenalty = p; best = mask; }
                ApplyMask(m, fn, size, mask);   // undo
            }
            ApplyMask(m, fn, size, best);
            FormatBits(m, fn, size, best);
            return m;
        }

        static void SetFn(bool[,] m, bool[,] fn, int x, int y, bool dark)
        {
            if (x < 0 || y < 0 || x >= m.GetLength(1) || y >= m.GetLength(0)) return;
            m[y, x] = dark;
            fn[y, x] = true;
        }

        static void Finder(bool[,] m, bool[,] fn, int cx, int cy)
        {
            for (int dy = -4; dy <= 4; dy++)
            {
                for (int dx = -4; dx <= 4; dx++)
                {
                    int dist = Math.Max(Math.Abs(dx), Math.Abs(dy));
                    SetFn(m, fn, cx + dx, cy + dy, dist != 2 && dist != 4);
                }
            }
        }

        // Level M is 0 in the two format bits.
        static void FormatBits(bool[,] m, bool[,] fn, int size, int mask)
        {
            int data = (0 << 3) | mask;
            int rem = data;
            for (int i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >> 9) * 0x537);
            int bits = ((data << 10) | rem) ^ 0x5412;

            for (int i = 0; i <= 5; i++) SetFn(m, fn, 8, i, Bit(bits, i));
            SetFn(m, fn, 8, 7, Bit(bits, 6));
            SetFn(m, fn, 8, 8, Bit(bits, 7));
            SetFn(m, fn, 7, 8, Bit(bits, 8));
            for (int i = 9; i < 15; i++) SetFn(m, fn, 14 - i, 8, Bit(bits, i));

            for (int i = 0; i < 8; i++) SetFn(m, fn, size - 1 - i, 8, Bit(bits, i));
            for (int i = 8; i < 15; i++) SetFn(m, fn, 8, size - 15 + i, Bit(bits, i));
            SetFn(m, fn, 8, size - 8, true);    // the always-dark module
        }

        static void VersionBits(bool[,] m, bool[,] fn, int size, int version)
        {
            int rem = version;
            for (int i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >> 11) * 0x1F25);
            int bits = (version << 12) | rem;
            for (int i = 0; i < 18; i++)
            {
                bool bit = Bit(bits, i);
                int a = size - 11 + i % 3;
                int b = i / 3;
                SetFn(m, fn, a, b, bit);
                SetFn(m, fn, b, a, bit);
            }
        }

        static void ApplyMask(bool[,] m, bool[,] fn, int size, int mask)
        {
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++)
                {
                    bool flip;
                    switch (mask)
                    {
                        case 0: flip = (x + y) % 2 == 0; break;
                        case 1: flip = y % 2 == 0; break;
                        case 2: flip = x % 3 == 0; break;
                        case 3: flip = (x + y) % 3 == 0; break;
                        case 4: flip = (x / 3 + y / 2) % 2 == 0; break;
                        case 5: flip = x * y % 2 + x * y % 3 == 0; break;
                        case 6: flip = (x * y % 2 + x * y % 3) % 2 == 0; break;
                        default: flip = ((x + y) % 2 + x * y % 3) % 2 == 0; break;
                    }
                    if (flip && !fn[y, x]) m[y, x] = !m[y, x];
                }
            }
        }

        // The four standard penalty rules.
        static int Penalty(bool[,] m, int size)
        {
            int score = 0;

            // 1: runs of five or more of one colour, in rows and in columns
            for (int a = 0; a < size; a++)
            {
                for (int dir = 0; dir < 2; dir++)
                {
                    int run = 1;
                    for (int b = 1; b < size; b++)
                    {
                        bool cur = dir == 0 ? m[a, b] : m[b, a];
                        bool prev = dir == 0 ? m[a, b - 1] : m[b - 1, a];
                        if (cur == prev) run++;
                        else
                        {
                            if (run >= 5) score += 3 + (run - 5);
                            run = 1;
                        }
                    }
                    if (run >= 5) score += 3 + (run - 5);
                }
            }

            // 2: 2x2 blocks of one colour
            for (int y = 0; y < size - 1; y++)
            {
                for (int x = 0; x < size - 1; x++)
                {
                    bool c = m[y, x];
                    if (c == m[y, x + 1] && c == m[y + 1, x] && c == m[y + 1, x + 1]) score += 3;
                }
            }

            // 3: something that looks like a finder (1:1:3:1:1) with four light modules beside it
            int[] p1 = new int[] { 1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0 };
            int[] p2 = new int[] { 0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1 };
            for (int a = 0; a < size; a++)
            {
                for (int b = 0; b + 11 <= size; b++)
                {
                    for (int dir = 0; dir < 2; dir++)
                    {
                        bool m1 = true, m2 = true;
                        for (int k = 0; k < 11 && (m1 || m2); k++)
                        {
                            int v = (dir == 0 ? m[a, b + k] : m[b + k, a]) ? 1 : 0;
                            if (v != p1[k]) m1 = false;
                            if (v != p2[k]) m2 = false;
                        }
                        if (m1) score += 40;
                        if (m2) score += 40;
                    }
                }
            }

            // 4: how far the dark share is from half
            int dark = 0;
            for (int y = 0; y < size; y++)
            {
                for (int x = 0; x < size; x++) { if (m[y, x]) dark++; }
            }
            int all = size * size;
            int k4 = (Math.Abs(dark * 20 - all * 10) + all - 1) / all - 1;
            score += k4 * 10;
            return score;
        }
    }
}
