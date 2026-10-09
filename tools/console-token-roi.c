/* Research observer: copy only the visible token regions from an existing
 * SpiceDisplay's borrowed primary surface. No connection, event dispatch,
 * pointer caching, background work or GIL release. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <pygobject.h>
#include <spice-client.h>
#include <spice-client-gtk.h>
#include <string.h>
#include <unistd.h>

static PyObject *snapshot(PyObject *self, PyObject *args)
{
    PyObject *object, *pixels = NULL, *result = NULL;
    int scale, channel_id, monitor_id, matches = 0;
    SpiceSession *session = NULL;
    SpiceChannel *channel = NULL;
    GArray *monitors = NULL;
    GList *channels = NULL;
    SpiceDisplayPrimary primary = {0};
    const char *error = NULL;
    if (!PyArg_ParseTuple(args, "Oi:snapshot", &object, &scale)) return NULL;
    if (scale != 1 && scale != 2) {
        PyErr_SetString(PyExc_ValueError, "scale must be1 or2"); return NULL;
    }
    if (!PyObject_TypeCheck(object, &PyGObject_Type) ||
        !SPICE_IS_DISPLAY(pygobject_get(object))) {
        PyErr_SetString(PyExc_TypeError, "existing SpiceDisplay required"); return NULL;
    }
    /* Surface creation/destruction and decode callbacks share this context.
     * Refuse calls from worker threads or outside its synchronous dispatch. */
    if (PyThread_get_thread_native_id() != (unsigned long)getpid() ||
        !g_main_context_is_owner(g_main_context_default())) {
        PyErr_SetString(PyExc_RuntimeError, "default main-loop ownership required"); return NULL;
    }
    g_object_get(pygobject_get(object), "session", &session, "channel-id", &channel_id,
                 "monitor-id", &monitor_id, NULL);
    if (!session) {error = "display has no session"; goto out;}
    channels = spice_session_get_channels(session);
    for (GList *item = channels; item; item = item->next) {
        int id;
        if (!SPICE_IS_DISPLAY_CHANNEL(item->data)) continue;
        g_object_get(item->data, "channel-id", &id, NULL);
        if (id == channel_id) {channel = item->data; matches++;}
    }
    if (matches != 1) {error = "need exactly one matching display channel"; goto out;}
    if (spice_display_channel_get_gl_scanout(SPICE_DISPLAY_CHANNEL(channel))) {
        error = "GL scanout unsupported"; goto out;
    }
    g_object_get(channel, "monitors", &monitors, NULL);
    if (!monitors || monitors->len != 1) {error = "one monitor mapping required"; goto out;}
    SpiceDisplayMonitorConfig map = g_array_index(monitors, SpiceDisplayMonitorConfig, 0);
    if ((monitor_id != -1 && (guint)monitor_id != map.id) || map.surface_id != 0 ||
        map.x != 0 || map.y != 0) {error = "unsupported monitor mapping"; goto out;}
    if (!spice_display_channel_get_primary(channel, map.surface_id, &primary)) {
        error = "primary surface unavailable"; goto out;
    }
    if (primary.format != SPICE_SURFACE_FMT_32_xRGB || !primary.data ||
        primary.width <= 0 || primary.height <= 0 ||
        primary.width > 8192 || primary.height > 8192 ||
        primary.stride < primary.width * 4 || primary.stride > 8192 * 8 ||
        map.width != (guint)primary.width || map.height != (guint)primary.height) {
        error = "unsupported primary format or geometry"; goto out;
    }
    int width = 320 * scale, height = 160 * scale;
    if (width > primary.width || height > primary.height) {error = "token ROI outside primary"; goto out;}
    Py_ssize_t size = (Py_ssize_t)width * height * 3;
    pixels = PyBytes_FromStringAndSize(NULL, size);
    if (!pixels) goto out;
    unsigned char *dest = (unsigned char *)PyBytes_AS_STRING(pixels);
    memset(dest, 0, size);
    for (int tile = 0; tile < 2; tile++) {
        int left = (tile ? 176 : 16) * scale;
        for (int y = 64 * scale; y < 160 * scale; y++) {
            const unsigned char *row = primary.data + (size_t)y * primary.stride;
            for (int x = left; x < left + 144 * scale; x++) {
                unsigned char *pixel = dest + ((size_t)y * width + x) * 3;
                /* Current supported Linux/x86 little-endian xRGB surface. */
                pixel[0] = row[x * 4 + 2]; pixel[1] = row[x * 4 + 1]; pixel[2] = row[x * 4];
            }
        }
    }
    result = Py_BuildValue("{s:O,s:i,s:i,s:i,s:i,s:i,s:i,s:i,s:i}",
        "pixels", pixels, "width", width, "height", height, "stride", width * 3,
        "channels", 3, "surface_width", primary.width, "surface_height", primary.height,
        "copied_pixels", 2 * 144 * 96 * scale * scale, "format", primary.format);
out:
    Py_XDECREF(pixels);
    if (monitors) g_array_unref(monitors);
    if (channels) g_list_free(channels);
    if (session) g_object_unref(session);
    if (error) PyErr_SetString(PyExc_ValueError, error);
    return result;
}

static PyMethodDef methods[] = {{"snapshot", snapshot, METH_VARARGS,
    "Copy bounded token ROIs from an existing display inside its main loop."}, {NULL, NULL, 0, NULL}};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "console_token_roi", NULL, -1, methods};
PyMODINIT_FUNC PyInit_console_token_roi(void)
{
#if !defined(__linux__) || G_BYTE_ORDER != G_LITTLE_ENDIAN
    PyErr_SetString(PyExc_ImportError, "only Linux little-endian xRGB validated"); return NULL;
#endif
    PyObject *gobject = pygobject_init(3, 0, 0);
    if (!gobject) return NULL;
    Py_DECREF(gobject);
    return PyModule_Create(&module);
}
