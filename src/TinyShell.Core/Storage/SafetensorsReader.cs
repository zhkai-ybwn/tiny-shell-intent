using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace TinyShell.Core.Storage;

public static class SafetensorsReader
{
    public static (float[] data, int rows, int cols) LoadEmbeddings(string safetensorsPath, string tensorName = "embeddings")
    {
        using var fs = File.OpenRead(safetensorsPath);
        using var reader = new BinaryReader(fs);

        ulong headerLength = reader.ReadUInt64();
        if (headerLength > 100 * 1024 * 1024)
        {
            throw new InvalidDataException($"Invalid safetensors header length: {headerLength}");
        }

        byte[] headerBytes = reader.ReadBytes((int)headerLength);
        string headerJson = Encoding.UTF8.GetString(headerBytes);

        using var doc = JsonDocument.Parse(headerJson);
        if (!doc.RootElement.TryGetProperty(tensorName, out var tensorElem))
        {
            throw new KeyNotFoundException($"Tensor '{tensorName}' not found in safetensors header");
        }

        string dtype = tensorElem.GetProperty("dtype").GetString()!;
        if (dtype != "F32")
        {
            throw new NotSupportedException($"Only F32 tensors are currently supported, found {dtype}");
        }

        var shapeElem = tensorElem.GetProperty("shape");
        int rows = shapeElem[0].GetInt32();
        int cols = shapeElem[1].GetInt32();

        var offsetsElem = tensorElem.GetProperty("data_offsets");
        long startOffset = offsetsElem[0].GetInt64();
        long endOffset = offsetsElem[1].GetInt64();
        long byteCount = endOffset - startOffset;

        long tensorDataStart = 8 + (long)headerLength + startOffset;
        fs.Seek(tensorDataStart, SeekOrigin.Begin);

        float[] floats = new float[rows * cols];
        byte[] rawBytes = reader.ReadBytes((int)byteCount);

        Buffer.BlockCopy(rawBytes, 0, floats, 0, (int)byteCount);
        return (floats, rows, cols);
    }
}
