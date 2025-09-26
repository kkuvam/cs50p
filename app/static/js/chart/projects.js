(function () {
  "use strict";

  /**
   * ------------------------------------------------------------------------
   *  Move the demo script to the footer before </body> 
   *  and edit the script for dynamic data needs.
   * ------------------------------------------------------------------------
   */

  // Colors
  const text_secondary_500 =   '#EC4899';
  const text_green_500     =   '#22C55E';

  const skin = localStorage.getItem('darkMode');
  if (skin === "dark") {
    var text_color     =   '#d4d4d4';
    var text_border_color     =  '#333333';
  } else {
    var text_color     =   '#525252';
    var text_border_color     =  'white';
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

  // Convert HEX TO RGBA
  function hexToRGBA(hex, opacity) {
    if (hex != null) {
      return 'rgba(' + (hex = hex.replace('#', '')).match(new RegExp('(.{' + hex.length/3 + '})', 'g')).map(function(l) { return parseInt(hex.length%2 ? l+l : l, 16) }).concat(isFinite(opacity) ? opacity : 1).join(',') + ')';
    }
  }

  // Demo Charts JS
  const myCharts = function () {
    Chart.defaults.color  =   text_color;

    // PROJECT PRODUCTIFITY CHART
    const chart_line_productifity = document.getElementById("ProductifityLine");
    if ( chart_line_productifity!= null) {
      const ctl_a = chart_line_productifity.getContext('2d');
      const ProductifityLine = new Chart(ctl_a, {
        type: 'line',
        data: {
          labels: ['1', '2', '3', '4', '5', '6', '7', '8'],
          datasets: [{
            label: 'Previous Week',
            data: [12, 21, 18, 19, 17, 21, 25, 28],
            fill: false,
            borderColor: text_secondary_500,
            borderDash: [5, 5],
            tension: 0.1,
            cubicInterpolationMode: 'monotone',
            pointBackgroundColor: text_secondary_500
          },
          {
            label: 'Current Week',
            data: [15, 22, 16, 17, 18, 24, 27, 24],
            fill: false,
            borderColor: text_primary_500,
            tension: 0.1,
            cubicInterpolationMode: 'monotone',
            pointBackgroundColor: text_primary_500
          }]
        },
        options: {
          animation: {
            y: {
              duration: 4000,
              from: 500
            }
          },
          responsive: true,
          plugins: {
            legend: {
              display: false,
            }
          },
          interaction: {
            mode: 'index',
            intersect: false,
          },
          scales: {
            x: {
              display: true,
              grid: {
                display: false
              },
              title: {
                display: true,
                text: 'August'
              }
            },
            y: {
              display: true,
              grid: {
                lineWidth: 0.5
              },
              position: 'right',
              title: {
                display: true,
                text: 'Task'
              }
            }
          }
        }
      })
    }
    // PROJECT DOUGHNUT CHART
    const chart_team = document.getElementById("TeamChart");
    if ( chart_team != null) {
      const ctd = chart_team.getContext('2d');
      const TeamChart = new Chart(ctd, {
        type: 'doughnut',
        data: {
          labels: ['Complete','In Porgress','Not Finished'],
          datasets: [{
            label: 'Progress',
            data: [74, 9, 17],
            backgroundColor: [
              text_green_500,
              text_primary_500,
              text_secondary_500,
            ],
            borderColor: text_border_color,
            hoverOffset: 4
          }]
        },
        options: {
          animation: {
            delay: 2000
          },
          plugins: {
            legend: {
              display: false,
            }
          }
        }
      })
    }
    // PROJECT BAR CHART
    const chart_budget = document.getElementById("BudgetChart");
    if ( chart_budget != null) {
      const ctb = chart_budget.getContext('2d');
      const BudgetChart = new Chart(ctb, {
        type: 'bar',
        data: {
          labels: ['UI/UX', 'Front End', 'Back End', 'Development'],
          datasets: [{
            label: 'Planned',
            data: [70, 41, 35, 83],
            backgroundColor: [
              text_primary_500
            ]
          },
          {
            label: 'Spend',
            data: [27, 17, 15, 19],
            backgroundColor: [
              hexToRGBA( text_primary_500, 0.8)
            ]
          },
          {
            label: 'Remaining',
            data: [24, 21, 35, 34],
            backgroundColor: [
              hexToRGBA( text_primary_500, 0.6)
            ]
          }]
        },
        options: {
          animation: {
            delay: 2000
          },
          plugins: {
            legend: {
              display: false,
            }
          },
          responsive: true,
          scales: {
            x: {
              grid: {
                display: false
              },
              stacked: true,
              display: true,
            },
            y: {
              stacked: true,
              grid: {
                display: false
              },
              ticks: {
                min: 0,
                max: 200,
                stepSize: 5,
                callback: function (value) {
                  return (value).toFixed(0) + 'k';
                },
              }
            }
          }
        }
      })
    }
  }

  /**
   * ------------------------------------------------------------------------
   * Launch Functions
   * ------------------------------------------------------------------------
   */
  myCharts();

})();
