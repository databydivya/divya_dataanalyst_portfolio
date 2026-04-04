use orders;

/*Query to display carton id, (len*width*height) as carton_vol and identify the optimum carton (carton with the least volume whose volume is greater than the total volume of all items (len * width * height * product_quantity)) for a given order whose order id is 10006, Assume all items of an order are packed into one single carton (box). (1 ROW) 
      [NOTE: CARTON TABLE]
      */

SELECT 
	CARTON_ID, (LEN * WIDTH * HEIGHT) as CARTON_VOL
FROM 
	CARTON
HAVING 
	CARTON_VOL > (
		SELECT 
			SUM(LEN * WIDTH * HEIGHT * PRODUCT_QUANTITY)
		FROM
			ORDER_ITEMS
		LEFT OUTER JOIN 
			PRODUCT
		ON 
			ORDER_ITEMS.PRODUCT_ID = PRODUCT.PRODUCT_ID
		WHERE ORDER_ID = 10006
	)
ORDER BY CARTON_VOL LIMIT 1;



/* Query to display details (customer id,customer fullname,order id,product quantity) of customers who bought more than ten (i.e. total order qty) products per shipped order. (11 ROWS) 
      [NOTE: TABLES TO BE USED - online_customer, order_header, order_items,]
*/

SELECT 
	OC.CUSTOMER_ID, OC.CUSTOMER_FNAME, OH.ORDER_ID, OT.PRODUCT_QUANTITY 
FROM 
	ONLINE_CUSTOMER OC
LEFT JOIN 
	ORDER_HEADER OH
ON 
	OC.CUSTOMER_ID = OH.CUSTOMER_ID
LEFT JOIN 
	ORDER_ITEMS OT
ON 
	OH.ORDER_ID = OT.ORDER_ID
WHERE ORDER_STATUS = 'Shipped'
GROUP BY OT.ORDER_ID
HAVING sum(OT.PRODUCT_QUANTITY) > 10
ORDER BY CUSTOMER_ID;


/* 9. Query to display the order_id, customer id and cutomer full name of customers along with (product_quantity) as total quantity of products shipped for order ids > 10060. (6 ROWS) 
      [NOTE: TABLES TO BE USED - online_customer, order_header, order_items]
*/

SELECT 
	OH.ORDER_ID, OC.CUSTOMER_ID, OC.CUSTOMER_FNAME, sum(OT.PRODUCT_QUANTITY) as TOTAL_QUANTITY 
FROM 
	ORDER_HEADER OH
LEFT JOIN 
	ONLINE_CUSTOMER OC
ON 
	OH.CUSTOMER_ID = OC.CUSTOMER_ID
LEFT JOIN 
	ORDER_ITEMS OT
ON 
	OH.ORDER_ID = OT.ORDER_ID
WHERE OH.ORDER_ID > 10060 AND ORDER_STATUS = 'Shipped'
GROUP BY OT.ORDER_ID;

/* Query to display product class description ,total quantity (sum(product_quantity),Total value (product_quantity * product price) and show which class of products have been shipped highest(Quantity) to countries outside India other than USA? Also show the total value of those items. (1 ROWS)
	   [NOTE:PRODUCT TABLE,ADDRESS TABLE,ONLINE_CUSTOMER TABLE,ORDER_HEADER TABLE,ORDER_ITEMS TABLE,PRODUCT_CLASS TABLE] 
       
*/

SELECT 
	PC.PRODUCT_CLASS_DESC, sum(OT.PRODUCT_QUANTITY) as TOTAL_QUANTITY, (OT.PRODUCT_QUANTITY*P.PRODUCT_PRICE) as TOTAL_VALUE
FROM 
	ADDRESS A
LEFT JOIN 
	ONLINE_CUSTOMER OC
ON 
	A.ADDRESS_ID = OC.ADDRESS_ID
LEFT JOIN 
	ORDER_HEADER OH
ON 
	OC.CUSTOMER_ID = OH.CUSTOMER_ID
LEFT JOIN 
	ORDER_ITEMS OT
ON 
	OH.ORDER_ID = OT.ORDER_ID
LEFT JOIN 
	PRODUCT P
ON 
	OT.PRODUCT_ID = P.PRODUCT_ID
LEFT JOIN 
	PRODUCT_CLASS PC
ON 
	P.PRODUCT_CLASS_CODE = PC.PRODUCT_CLASS_CODE
WHERE OH.ORDER_STATUS = 'Shipped' AND A.COUNTRY != 'INDIA' AND A.COUNTRY!= 'USA'
GROUP BY OT.PRODUCT_ID
ORDER BY TOTAL_QUANTITY DESC LIMIT 1;

 







