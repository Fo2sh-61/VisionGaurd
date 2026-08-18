import onnxruntime as ort

session = ort.InferenceSession("best-wave.onnx")

print("Model loaded successfully!")

print("Input:")
for i in session.get_inputs():
    print(i.name, i.shape)

print("\nOutput:")
for o in session.get_outputs():
    print(o.name, o.shape)

meta = session.get_modelmeta().custom_metadata_map
print("\nTask:", meta.get("task"))
print("Classes:", meta.get("names"))