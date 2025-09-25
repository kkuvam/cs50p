(function () {
  "use strict";

  /**
   * ------------------------------------------------------------------------
   *  Move the demo script to the footer before </body> 
   *  and edit the script for dynamic data needs.
   * ------------------------------------------------------------------------
   */

  // Colors
  const skin = localStorage.getItem('darkMode');
  if (skin === "dark") {
    var text_gray_500     =   '#d4d4d4';
  } else {
    var text_gray_500     =   '#525252';
  }

  const themeColor = localStorage.getItem('selectedTheme');
  if (themeColor === "red") {
    var text_primary_500    =   '#ef4444';
  } else if (themeColor === "yellow") {
    var text_primary_500    =   '#eab308';
  } else if (themeColor === "green") {
    var text_primary_500    =   '#22c55e';
  } else if (themeColor === "sky") {
    var text_primary_500    =   '#0ea5e9';
  } else if (themeColor === "blue") {
    var text_primary_500    =   '#3b82f6';
  } else if (themeColor === "lime") {
    var text_primary_500    =   '#84cc16';
  } else if (themeColor === "purple") {
    var text_primary_500    =   '#a855f7';
  } else if (themeColor === "pink") {
    var text_primary_500    =   '#ec4899';
  } else if (themeColor === "rosewood") {
    var text_primary_500    =   '#9F2A2A';
  } else if (themeColor === "genoa") {
    var text_primary_500    =   '#166064';
  } else if (themeColor === "seance") {
    var text_primary_500    =   '#7E2A9F';
  } else if (themeColor === "gold") {
    var text_primary_500    =   '#B58429';
  } else if (themeColor === "orange") {
    var text_primary_500    =   '#f97316';
  } else {
    var text_primary_500    =   '#6366f1';
  }

  const text_secondary_500 =   '#EC4899';
  const text_green_500     =   '#22c55e';

  // Demo Vector Maps
  const myMaps = function () {
    // Maps
    const worldmap = document.getElementById('worldmap');
    if ( worldmap != null) {
      const map = new jsVectorMap({
        selector: "#worldmap",
        map: "world",
        visualizeData: {
          scale: [ text_gray_500 , text_primary_500 ],
          values: {
            IN: 259,
            US: 220,
            ID: 175,
            CA: 160,
            BR: 175,
            AR: 155,
            ES: 235,
            UK: 227,
            RU: 176
          }
        }
      });
    }
  }
  
  // Demo text editor
  const myEditor = function () {
    const text_editor = document.querySelectorAll(".texteditor");
    if ( text_editor != null) {
      for( let i = 0; i < text_editor.length; i++)
      {
        const simplemde = new SimpleMDE({ 
          element: text_editor[i],
          toolbarTips: false,
          hideIcons: ["guide"]
        });
      }
    };
  }

  // Demo Calender schedule
  const myCalendar = function () {
    // Calendar Event
    const fullcalendars = document.getElementById('calendar');
    if ( fullcalendars != null) {
      document.addEventListener('DOMContentLoaded', function() {
        const calendarEl = document.getElementById('calendar');
        const date = new Date();
        const month = new Date();
        const dates = date.getFullYear().toString() + '-' + (date.getMonth() + 1).toString().padStart(2, 0) + '-' + date.getDate().toString().padStart(2, 0);
        const yearmonth = month.getFullYear().toString() + '-' + (month.getMonth() + 1).toString().padStart(2, 0) + '-';
        const calendar = new FullCalendar.Calendar(calendarEl, {
          initialView: 'dayGridMonth',
          initialDate: dates,
          headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
          },
          events: [
            {
              title: 'All Day Event',
              start: yearmonth + '01',
              backgroundColor: text_secondary_500,
              borderColor: text_secondary_500
            },
            {
              title: 'Long Event',
              start: yearmonth + '03',
              end: yearmonth + '06'
            },
            {
              groupId: '999',
              title: 'Repeating Event',
              start: yearmonth + '09T16:00:00',
              backgroundColor: text_green_500,
              borderColor: text_green_500
            },
            {
              groupId: '999',
              title: 'Repeating Event',
              start: yearmonth + '16T16:00:00',
              backgroundColor: text_gray_500,
              borderColor: text_gray_500
            },
            {
              title: 'Conference',
              start: '11',
              end: yearmonth + '13'
            },
            {
              title: 'Meeting',
              start: yearmonth + '12T10:30:00',
              end: yearmonth + '12T12:30:00',
              backgroundColor: text_secondary_500,
              borderColor: text_secondary_500
            },
            {
              title: 'Lunch',
              start: yearmonth + '12T12:00:00'
            },
            {
              title: 'Meeting',
              start: yearmonth + '12T14:30:00',
              backgroundColor: text_secondary_500,
              borderColor: text_secondary_500
            },
            {
              title: 'Birthday Party',
              start: yearmonth + '20T07:00:00'
            },
            {
              title: 'Evant with link',
              url: 'http://google.com/',
              start: yearmonth + '28',
              backgroundColor: text_green_500,
              borderColor: text_green_500
            }
          ],
          eventColor: text_primary_500
        });
        calendar.render();

      });
    }
  }

  // Dropzone uploader
  const myUploader = function () {
    // dropzone
    const dropzone_class = document.querySelectorAll(".multiple-dropzone");

    if ( dropzone_class != null) {
      for( let i = 0; i < dropzone_class.length; i++){
        const myDropzone = new Dropzone( dropzone_class[i], {
          addRemoveLinks: true,
          uploadMultiple: true,
          parallelUploads: 100,
          maxFiles: 5,
          paramName: 'file',
          clickable: true,
          url: '#'
        });
        Dropzone.autoDiscover = false;
      }
    }

    const dropzone_single = document.querySelectorAll(".single-dropzone");
    if ( dropzone_single != null) {
      for( let i = 0; i < dropzone_single.length; i++){
        const myDropzone = new Dropzone( dropzone_single[i], {
          addRemoveLinks: true,
          uploadMultiple: false,
          maxFiles: 1,
          init: function() {
            this.on('addedfile', function(file) {
              if (this.files.length > 1) {
                this.removeFile(this.files[0]);
              }
            });
          },
          paramName: 'file',
          clickable: true,
          url: '#'
        });
        Dropzone.autoDiscover = false;
      }
    }
  }

  // Lightbox
  const myLightbox = function () {
    // GLightbox
    const lightbox_class = document.querySelector(".glightbox3");
    if ( lightbox_class != null) {
      const lightbox = GLightbox({
        selector: '.glightbox3',
        touchNavigation: true,
        loop: true,
        autoplayVideos: true
      });
    }
  }

  /**
   * ------------------------------------------------------------------------
   * Launch Functions
   * ------------------------------------------------------------------------
   */
  myMaps();
  myEditor();
  myCalendar();
  myUploader();
  myLightbox();

})();