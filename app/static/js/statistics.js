/**
 * statistics.js - Handles all statistics functionality for the Coupon Master app
 * This script is loaded dynamically when the statistics modal is opened
 */

// Global variables for statistics
let companiesData = [];
let originalTimelineData = [];
let selectedCompanies = new Set(['all']);
let pieChart = null;
let timelineChart = null;
let lastClickedIndex = -1;
let isShiftKeyPressed = false;

/**
 * Main function to render all statistical charts and initialize filtering
 */
function renderSavingsCharts() {
  try {
    // Get data passed from the server
    companiesData = JSON.parse('{{ companies_stats|safe }}');
    originalTimelineData = JSON.parse('{{ timeline_data|safe }}');

    // Verify data is valid
    if (!Array.isArray(companiesData) || companiesData.length === 0) {
      console.error("Error: companies_stats is empty or not an array");
      companiesData = [];
    }

    // Organize data for chart format
    const pieData = companiesData.map(item => ({
      company: item.company,
      value: item.savings || 0
    }));

    // Sort companies by savings amount (high to low)
    const sortedCompanies = companiesData
      .sort((a, b) => (b.savings || 0) - (a.savings || 0))
      .map(item => item.company);
    
    // Initialize all visualization components
    createCompanyFilters(sortedCompanies);
    updateStatisticsCards(companiesData);
    updateSavingsTable(companiesData);
    createPieChart(pieData);
    createTimelineChart(originalTimelineData);
    
    // Add resize event listener for better mobile responsiveness
    window.addEventListener('resize', function() {
      if (pieChart) {
        const isMobile = window.innerWidth < 768;
        // Update legend position based on screen size
        if (pieChart.options && pieChart.options.plugins && pieChart.options.plugins.legend) {
          pieChart.options.plugins.legend.position = isMobile ? 'bottom' : 'right';
          pieChart.update();
        }
      }
    });
  } catch (e) {
    console.error("Error parsing statistics data:", e);
    companiesData = [];
  }
}

/**
 * Update statistics cards based on filtered data
 * @param {Array} data - The filtered companies data
 */
function updateStatisticsCards(data) {
  let totalSavings = 0;
  let totalPossibleValue = 0;
  let totalCoupons = 0;
  let activeCoupons = 0;
  let totalUsagePercentage = 0;

  data.forEach(company => {
    totalSavings += company.savings || 0;
    totalPossibleValue += company.total_value || 0;
    totalCoupons += company.coupons_count || 0;
    activeCoupons += company.active_coupons || 0;
    totalUsagePercentage += ((company.usage_percentage || 0) * (company.coupons_count || 0));
  });

  const avgUsagePercentage = totalCoupons > 0 ? totalUsagePercentage / totalCoupons : 0;
  const savingsPercentage = totalPossibleValue > 0 ? (totalSavings / totalPossibleValue) * 100 : 0;

  // Update card information
  document.querySelector('#total-savings-card .big-number').textContent = Math.round(totalSavings).toString() + ' ₪';
  document.querySelector('#total-savings-card p').textContent = 'מתוך ' + Math.round(totalPossibleValue).toString() + ' ₪ אפשריים';
  
  document.querySelector('#savings-percentage-card .big-number').textContent = Math.round(savingsPercentage).toString() + '%';
  
  document.querySelector('#total-coupons-card .big-number').textContent = totalCoupons.toString();
  document.querySelector('#total-coupons-card p').textContent = activeCoupons.toString() + ' מתוכם פעילים';
  
  document.querySelector('#average-usage-card .big-number').textContent = Math.round(avgUsagePercentage).toString() + '%';
}

/**
 * Create filter controls for companies with support for multiple selections and shift+click
 * @param {Array} companies - List of company names
 */
function createCompanyFilters(companies) {
  const filtersContainer = document.getElementById('company-filters');
  filtersContainer.innerHTML = '';
  
  // Add "All" filter option
  const allFilter = document.createElement('div');
  allFilter.className = 'company-filter-item active';
  allFilter.dataset.company = 'all';
  allFilter.dataset.index = -1;
  allFilter.innerHTML = '<span>הכל</span>';
  filtersContainer.appendChild(allFilter);
  
  // Add filter for each company
  companies.forEach((company, index) => {
    const filterItem = document.createElement('div');
    filterItem.className = 'company-filter-item';
    filterItem.dataset.company = company;
    filterItem.dataset.index = index;
    filterItem.innerHTML = `<span>${company}</span>`;
    filtersContainer.appendChild(filterItem);
  });
  
  // Prevent text selection when using Shift+Click
  document.querySelectorAll('.company-filter-item').forEach(item => {
    item.addEventListener('mousedown', function(e) {
      if (isShiftKeyPressed) {
        e.preventDefault();
      }
    });
  });

  // Add click event with support for multiple selection
  document.querySelectorAll('.company-filter-item').forEach(item => {
    item.addEventListener('click', function(e) {
      const companyName = this.dataset.company;
      const currentIndex = parseInt(this.dataset.index);
      
      // Handle click on "All"
      if (companyName === 'all') {
        document.querySelectorAll('.company-filter-item').forEach(i => {
          i.classList.remove('active');
        });
        this.classList.add('active');
        selectedCompanies.clear();
        selectedCompanies.add('all');
        lastClickedIndex = -1;
      } else {
        // Handle Shift+Click for multiple selection
        if (isShiftKeyPressed && lastClickedIndex !== -1 && lastClickedIndex !== currentIndex) {
          // Remove "All" if selected
          const allItem = document.querySelector('.company-filter-item[data-company="all"]');
          allItem.classList.remove('active');
          selectedCompanies.delete('all');
          
          // Set the range for selection
          const start = Math.min(lastClickedIndex, currentIndex);
          const end = Math.max(lastClickedIndex, currentIndex);

          // Collect all elements in their natural order
          const allItems = Array.from(document.querySelectorAll('.company-filter-item'));
          const itemsInRange = allItems.filter(item => {
            const idx = parseInt(item.dataset.index);
            return idx >= start && idx <= end && idx !== -1; // Don't include "All" option
          });

          // Select all companies in range
          itemsInRange.forEach(item => {
            if (!item.classList.contains('active')) {
              item.classList.add('active');
              selectedCompanies.add(item.dataset.company);
            }
          });
        } else {
          // Toggle active/inactive state for current company (without Shift)
          // Remove "All" if a specific company is selected
          const allItem = document.querySelector('.company-filter-item[data-company="all"]');
          allItem.classList.remove('active');
          selectedCompanies.delete('all');
          
          // Toggle active/inactive state for current company
          if (this.classList.contains('active')) {
            this.classList.remove('active');
            selectedCompanies.delete(companyName);
            
            // If no companies are selected, revert to "All"
            if (document.querySelectorAll('.company-filter-item.active').length === 0) {
              allItem.classList.add('active');
              selectedCompanies.add('all');
              lastClickedIndex = -1;
            }
          } else {
            this.classList.add('active');
            selectedCompanies.add(companyName);
          }
        }
        
        // Save the last clicked index (for use with Shift+Click)
        if (currentIndex >= 0) {
          lastClickedIndex = currentIndex;
        }
      }
      
      filterAndUpdateCharts();
    });
  });
}

/**
 * Filter data and update charts/table based on selected companies
 */
function filterAndUpdateCharts() {
  let filteredData;
  
  if (selectedCompanies.has('all')) {
    filteredData = companiesData;
    
    // Update all charts and tables
    const pieData = companiesData.map(item => ({
      company: item.company,
      value: item.savings || 0
    }));
    
    updatePieChart(pieData);
    updateTimelineChart(originalTimelineData);
  } else {
    // Filter data by selected companies
    filteredData = companiesData.filter(item => selectedCompanies.has(item.company));
    
    // Update pie chart
    const filteredPieData = filteredData.map(item => ({
      company: item.company,
      value: item.savings || 0
    }));
    
    updatePieChart(filteredPieData);
    
    // Filter timeline data by selected companies
    if (originalTimelineData && originalTimelineData.length) {
      // Filter timeline data based on selected companies
      const filteredTimelineData = originalTimelineData.filter(item => {
        // If the timeline data has company information
        if (item.company) {
          return selectedCompanies.has(item.company);
        }
        // If there's no company info, keep the data point
        return true;
      });
      
      updateTimelineChart(filteredTimelineData.length > 0 ? filteredTimelineData : originalTimelineData);
    }
  }
  
  updateStatisticsCards(filteredData);
  updateSavingsTable(filteredData);
}

/**
 * Update the savings table with company-specific savings percentages
 * @param {Array} data - The filtered companies data
 */
function updateSavingsTable(data) {
  const tableBody = document.querySelector("#savingsTable tbody");
  tableBody.innerHTML = '';
  
  data.forEach(item => {
    // Savings percentage of the company's coupon value
    const percentOfCompany = item.total_value > 0 ? 
      (item.savings / item.total_value * 100).toFixed(1) : "0.0";
    
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${item.company}</td>
      <td>${(item.savings || 0).toFixed(2)} ₪</td>
      <td>${percentOfCompany}%</td>
    `;
    tableBody.appendChild(row);
  });
}

/**
 * Create pie chart for company savings distribution
 * @param {Array} pieData - Data for the pie chart
 */
function createPieChart(pieData) {
  if (typeof Chart !== 'undefined') {
    document.getElementById('companySavingsChart').innerHTML = '';
    const canvas = document.createElement('canvas');
    document.getElementById('companySavingsChart').appendChild(canvas);
    const ctx = canvas.getContext('2d');
    
    // Standard colors for the pie chart
    const colors = [
      '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', 
      '#FF9F40', '#50AF95', '#7E57C2', '#2196F3', '#F44336',
      '#4CAF50', '#FF5722', '#9C27B0', '#673AB7', '#3F51B5'
    ];
    
    // Create enough colors for all data points
    const backgroundColors = [];
    for (let i = 0; i < pieData.length; i++) {
      backgroundColors.push(colors[i % colors.length]);
    }
          
    // Create mapping of full company details for tooltip display
    const companyDetailsMap = {};
    pieData.forEach((item, index) => {
      // Find the full company data
      const fullCompanyData = companiesData.find(c => c.company === item.company);
      if (fullCompanyData) {
        companyDetailsMap[item.company] = fullCompanyData;
      }
    });
    
    // Responsive legend position based on screen size
    const isMobile = window.innerWidth < 768;
    
    pieChart = new Chart(ctx, {
      type: 'pie',
      data: {
        labels: pieData.map(d => d.company),
        datasets: [{
          data: pieData.map(d => d.value),
          backgroundColor: backgroundColors
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: isMobile ? 'bottom' : 'right',
            labels: { 
              font: { size: isMobile ? 10 : 12 },
              boxWidth: isMobile ? 10 : 15
            }
          },
          tooltip: {
            rtl: true, // RTL text direction
            textDirection: 'rtl',
            // Custom tooltip styling
            backgroundColor: 'rgba(0, 0, 0, 0.8)',
            titleFont: {
              size: 14
            },
            bodyFont: {
              size: 14
            },
            padding: 12,
            titleAlign: 'right',
            bodyAlign: 'right',
            callbacks: {
              // Handle text lines for RTL display
              label: function(context) {
                const company = context.label;
                const value = context.raw;
                const companyData = companiesData.find(c => c.company === company);
                
                if (!companyData) return [`${value.toFixed(2)} :${company}`];
                
                // Build text lines with colon on the left side
                // so in RTL display text appears with colon on right side
                const lines = [
                  `${value.toFixed(2)} :${company}`
                ];
                
                // Calculate percentage of total savings
                const totalSavings = companiesData.reduce((sum, c) => sum + (c.savings || 0), 0);
                const savingsPercentage = totalSavings > 0 ? ((value / totalSavings) * 100).toFixed(1) : "0.0";
                lines.push(`${savingsPercentage}% :אחוז מסך החיסכון`);
                
                // Coupon count if available
                if (companyData.coupons_count !== undefined) {
                  lines.push(`${companyData.coupons_count} :מספר קופונים`);
                }
                
                // Usage percentage if available
                if (companyData.usage_percentage !== undefined) {
                  lines.push(`${companyData.usage_percentage.toFixed(1)}% :אחוז ניצול`);
                }
                
                // Remaining value if available
                if (companyData.remaining_value !== undefined) {
                  lines.push(`₪ ${companyData.remaining_value.toFixed(2)} :יתרה`);
                }
                
                return lines;
              },
              // Adjust tooltip title order
              title: function(tooltipItems) {
                return ''; // Optional: remove original title
              }
            }
          }
        }
      }
    });
  } else {
    document.getElementById('companySavingsChart').innerHTML = '<p style="text-align:center;padding-top:80px;">לצפייה בגרף יש להתקין ספריית Chart.js</p>';
  }
}

/**
 * Update pie chart data
 * @param {Array} pieData - Updated data for the pie chart
 */
function updatePieChart(pieData) {
  if (pieChart) {
    pieChart.data.labels = pieData.map(d => d.company);
    pieChart.data.datasets[0].data = pieData.map(d => d.value);
    pieChart.update();
  }
}

/**
 * Create timeline (line) chart with real data
 * @param {Array} timelineData - Data for the timeline chart
 */
function createTimelineChart(timelineData) {
  if (typeof Chart !== 'undefined') {
    document.getElementById('timelineChart').innerHTML = '';
    const canvas = document.createElement('canvas');
    document.getElementById('timelineChart').appendChild(canvas);
    const ctx = canvas.getContext('2d');
    
    // Responsive font size based on screen size
    const isMobile = window.innerWidth < 768;
    const fontSize = isMobile ? 10 : 12;
    
    // Add plugin for custom tooltips
    const customTooltip = {
      id: 'customTooltip',
      afterDraw(chart, args, options) {
        const { ctx } = chart;
        ctx.canvas.style.direction = 'rtl';
      }
    };
    
    timelineChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: timelineData.map(d => d.month),
        datasets: [{
          label: 'חיסכון חודשי (ש"ח)',
          data: timelineData.map(d => d.value),
          borderColor: '#3498db',
          backgroundColor: 'rgba(52, 152, 219, 0.2)',
          borderWidth: 2,
          fill: true
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { 
          y: { 
            beginAtZero: true,
            ticks: {
              font: { size: fontSize }
            }
          },
          x: {
            ticks: {
              font: { size: fontSize },
              maxRotation: isMobile ? 45 : 0
            }
          }
        },
        plugins: {
          tooltip: {
            rtl: true,
            textDirection: 'rtl',
            backgroundColor: 'rgba(0, 0, 0, 0.8)',
            titleFont: {
              size: 14
            },
            bodyFont: {
              size: 14
            },
            padding: 12,
            titleAlign: 'right',
            bodyAlign: 'right',
            displayColors: false,
            position: 'nearest',
            caretSize: 6,
            callbacks: {
              label: function(context) {
                const index = context.dataIndex;
                const data = timelineData[index];
                
                if (!data) return [`חיסכון: ${context.raw.toFixed(2)} ₪`];
                
                const lines = [];
                lines.push(`סה"כ חיסכון בחודש זה: ${context.raw.toFixed(2)} ₪`);
                
                if (data.original_value !== undefined) {
                  lines.push(`סה"כ ערך מקורי: ${data.original_value.toFixed(2)} ₪`);
                }
                
                if (data.remaining_value !== undefined) {
                  lines.push(`סה"כ ערך שנותר: ${data.remaining_value.toFixed(2)} ₪`);
                }
                
                if (data.coupons_count !== undefined) {
                  lines.push(`מספר קופונים שנקנו: ${data.coupons_count}`);
                }
                
                if (data.discount_percentage !== undefined) {
                  lines.push(`אחוז הנחה ממוצע: ${data.discount_percentage.toFixed(1)}%`);
                }
                
                if (data.companies && data.companies.length > 0) {
                  lines.push(`חברות בחודש זה:`);
                  data.companies.forEach(company => {
                    lines.push(`• ${company}`);
                  });
                }
                
                return lines;
              },
              title: function(tooltipItems) {
                return tooltipItems[0].label; // Month
              },
              labelTextColor: function(context) {
                return 'white';
              }
            }
          },
          legend: {
            labels: { 
              font: { size: fontSize }
            }
          }
        },
        layout: {
          padding: {
            left: 10,
            right: 10
          }
        }
      },
      plugins: [customTooltip]
    });
    
    // Add styles directly to canvas and tooltips
    canvas.style.direction = 'rtl';
    document.getElementById('timelineChart').style.direction = 'rtl';
    
    // Add global styles for tooltips
    const tooltipStyles = document.createElement('style');
    tooltipStyles.textContent = `
      #timelineChart {
        direction: rtl !important;
        text-align: right !important;
      }
      #timelineChart canvas {
        direction: rtl !important;
      }
      .chartjs-tooltip {
        direction: rtl !important;
        text-align: right !important;
      }
      .chartjs-tooltip-body {
        direction: rtl !important;
        text-align: right !important;
      }
      .chartjs-tooltip-title {
        text-align: right !important;
      }
      #tooltip-el {
        direction: rtl !important;
        text-align: right !important;
      }
      .chartjs-tooltip p {
        margin: 2px 0;
        padding-right: 5px;
        text-align: right;
      }
    `;
    document.head.appendChild(tooltipStyles);
  } else {
    document.getElementById('timelineChart').innerHTML = '<p style="text-align:center;padding-top:80px;">לצפייה בגרף יש להתקין ספריית Chart.js</p>';
  }
}

/**
 * Update timeline chart data
 * @param {Array} timelineData - Updated data for the timeline chart
 */
function updateTimelineChart(timelineData) {
  if (timelineChart) {
    timelineChart.data.labels = timelineData.map(d => d.month);
    timelineChart.data.datasets[0].data = timelineData.map(d => d.value);
    timelineChart.update();
  }
}

// Add specific CSS for timeline chart tooltips
document.addEventListener('DOMContentLoaded', function() {
  const style = document.createElement('style');
  style.textContent = `
    #timelineChart canvas {
      direction: rtl !important;
    }
    .chartjs-tooltip {
      direction: rtl !important;
      text-align: right !important;
    }
    #timelineChart {
      direction: rtl !important;
    }
  `;
  document.head.appendChild(style);
});

// Track shift key state for multi-selection
document.addEventListener('keydown', function(e) {
  if (e.key === 'Shift') {
    isShiftKeyPressed = true;
  }
});

document.addEventListener('keyup', function(e) {
  if (e.key === 'Shift') {
    isShiftKeyPressed = false;
  }
});

// Close modal when clicking outside
window.addEventListener("click", function(e) {
  const statsModal = document.getElementById("statsModal");
  if (e.target === statsModal) {
    statsModal.classList.remove("active");
  }
});
