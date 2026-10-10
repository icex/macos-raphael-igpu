/* Isolated renderer control: synthetic CPU primary, no VM or device exposure. */
#include "config.h"
#include "spice-widget-priv.h"
#include <glib/gstdio.h>
#include <stdlib.h>
static SpiceDisplay *display;
static gboolean finish(gpointer unused) {
    SpiceDisplayPrivate *d=display->priv;
    g_print("FIXTURE active=%d failed=%d renders=%"G_GUINT64_FORMAT"\n",d->raw_gl.active,d->raw_gl.failed,d->raw_gl.renders);
    gtk_main_quit();return FALSE;
}
int main(int argc,char **argv) {
    GtkWidget *window;SpiceSession *session;SpiceDisplayPrivate *d;gint x,y;
    if(argc!=7)return 2;
    gint width=atoi(argv[1]),height=atoi(argv[2]),vw=atoi(argv[3]),vh=atoi(argv[4]);
    if(width<1||height<1||width>4096||height>2160||vw<1||vh<1)return 2;
    gtk_init(&argc,&argv);session=spice_session_new();display=spice_display_new(session,0);d=display->priv;
    g_object_set(display,"scaling",TRUE,"resize-guest",FALSE,"disable-inputs",TRUE,NULL);
    d->canvas.width=width;d->canvas.height=height;d->canvas.stride=(width+3)*4;
    d->canvas.format=SPICE_SURFACE_FMT_32_xRGB;d->canvas.convert=FALSE;
    d->canvas.data_origin=g_malloc0((gsize)d->canvas.stride*height);d->canvas.data=d->canvas.data_origin;
    for(y=0;y<height;y++)for(x=0;x<width;x++){
        guchar *p=(guchar*)d->canvas.data_origin+(gsize)y*d->canvas.stride+x*4;
        p[0]=(x*7+y*3)%256;p[1]=(y*5)%256;p[2]=(x*3)%256;p[3]=(x+y)%256;
    }
    d->area=(GdkRectangle){0,0,width,height};d->ready=TRUE;d->monitor_ready=TRUE;d->mouse_mode=SPICE_MOUSE_MODE_CLIENT;
    window=gtk_window_new(GTK_WINDOW_TOPLEVEL);gtk_window_set_title(GTK_WINDOW(window),"Raphael isolated GL renderer control");
    gtk_window_set_default_size(GTK_WINDOW(window),vw,vh);gtk_widget_set_size_request(GTK_WIDGET(display),vw,vh);
    gtk_window_set_resizable(GTK_WINDOW(window),FALSE);gtk_container_add(GTK_CONTAINER(window),GTK_WIDGET(display));gtk_widget_show_all(window);
    GdkRectangle rect={0,0,width,height};spice_raw_gl_invalidate(display,&rect);
    g_timeout_add(2500,finish,NULL);gtk_main();
    gint result=d->raw_gl.active&&!d->raw_gl.failed?0:1;
    /* Process exit owns the synthetic canvas; no channel was created. */
    return result;
}
